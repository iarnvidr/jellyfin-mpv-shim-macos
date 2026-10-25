-- AppKit editing and accessibility for the custom-drawn browser. Kept in the
-- renderer's scope so actions use its current focus, clipping and input paths.
;(function()
    local old_state, old_changed = tb_state, tb_changed
    local restoring = false
    local function snapshot(tb)
        return {text=tb.text, cursor=tb.cursor, sel=tb.sel}
    end
    tb_state = function(node)
        local tb = old_state(node)
        if not tb.mac_history then
            tb.mac_history = {undo={}, redo={}, last=snapshot(tb)}
        end
        return tb
    end
    tb_changed = function(node, tb)
        local history = tb.mac_history
        if history and not restoring and history.last.text ~= tb.text then
            table.insert(history.undo, history.last)
            if #history.undo > 100 then table.remove(history.undo, 1) end
            history.redo = {}
        end
        old_changed(node, tb)
        if history then history.last = snapshot(tb) end
    end
    local function edit(operation)
        local node = focused_node()
        if not node or node.dis then return end
        local tb = tb_state(node)
        if operation == 'UNDO' or operation == 'REDO' then
            local history = tb.mac_history
            local from = operation == 'UNDO' and history.undo or history.redo
            local to = operation == 'UNDO' and history.redo or history.undo
            local prior = table.remove(from)
            if prior then
                table.insert(to, snapshot(tb))
                tb.text, tb.cursor, tb.sel = prior.text, prior.cursor, prior.sel
                restoring = true
                tb_changed(node, tb)
                restoring = false
            end
        elseif operation == 'SHOME' or operation == 'SEND' then
            if not tb.sel then tb.sel = tb.cursor end
            tb.cursor = operation == 'SHOME' and 0 or #tb.text
            tb_fix_shift(node, tb); request_render()
        else
            tb_key(operation)
        end
    end
    mp.register_script_message('jellyfin-native-edit', edit)
    local last_edit, last_ax, last_scene
    local generation = 0
    mp.add_periodic_timer(0.1, function()
        local node = focused_node()
        local tb = node and tb_state(node)
        local editing = {focused=node ~= nil,
            selection=tb ~= nil and not node.mask and tb.sel ~= nil and tb.sel ~= tb.cursor,
            undo=tb ~= nil and #tb.mac_history.undo > 0,
            redo=tb ~= nil and #tb.mac_history.redo > 0}
        local encoded = utils.format_json(editing)
        if encoded ~= last_edit then
            last_edit = encoded
            mp.set_property_native('user-data/jellyfin-native-edit', editing)
        end
        compute_geo()
        if state.scene ~= last_scene then
            last_scene = state.scene
            generation = generation + 1
        end
        local controls = {}
        local modal = modal_active()
        for index, n in ipairs(state.nodes or {}) do
            if visible(n) and (not modal or n.mod) then
                local role = n.t == 'textbox' and 'text' or n.t == 'slider' and 'slider'
                    or n.t == 'checkbox' and 'checkbox' or n.t == 'dropdown' and 'popup'
                    or n.click and 'button' or n.t == 'text' and 'label'
                if role then
                    local x, y, clip = eff(n)
                    local x1, y1 = math.max(x, 0), math.max(y, 0)
                    local x2, y2 = math.min(x+n.w, state.w), math.min(y+n.h, state.h)
                    if clip then
                        x1, y1 = math.max(x1, clip.x1), math.max(y1, clip.y1)
                        x2, y2 = math.min(x2, clip.x2), math.min(y2, clip.y2)
                    end
                    local text = n.ax_label or n.text or n.label or n.tip or n.ph or ''
                    local value = n.value
                    if role == 'text' then
                        value = n.mask and '' or tb_state(n).text
                        text = n.ax_label or n.ph or n.tip or 'Text field'
                    end
                    if role == 'popup' then value = (n.items or {})[(dd_state(n).sel or 0)+1] end
                    controls[#controls+1] = {id=n.id or ('label-'..index), role=role,
                        label=n.mask and (n.ph or n.tip or 'Password') or text, value=value, secure=n.mask or false,
                        enabled=not n.dis, x=x1, y=y1, w=x2-x1, h=y2-y1,
                        focused=state.focus == n.id or state.nav == n.id, min=n.min, max=n.max, generation=generation}
                    if role == 'popup' and state.dd_open == n.id then
                        for option, label in ipairs(n.items or {}) do
                            controls[#controls+1] = {id=n.id..':option:'..option, control=n.id,
                                role='button', label=label, enabled=not n.dis, generation=generation,
                                option=option-1, x=x1, y=y1, w=x2-x1, h=y2-y1}
                        end
                    end
                end
            end
        end
        local model = {w=state.w, h=state.h, nodes=controls}
        encoded = utils.format_json(model)
        if encoded ~= last_ax then
            last_ax = encoded
            mp.set_property_native('user-data/jellyfin-accessibility', model)
        end
    end)
    mp.register_script_message('jellyfin-accessibility-action', function(json)
        local action = utils.parse_json(json)
        if not action or action.generation ~= generation or state.scene ~= last_scene then return end
        local n = state.byid[action.control or action.id]
        if not n or n.dis or not visible(n) or (modal_active() and not n.mod) then return end
        if action.action == 'focus' then
            if n.t == 'textbox' then focus_textbox(n) else nav_set(n) end
        elseif action.action == 'set' and n.t == 'textbox' and type(action.value) == 'string' then
            focus_textbox(n)
            local tb = tb_state(n)
            tb.text, tb.cursor, tb.sel = action.value, #action.value, nil
            tb_changed(n, tb)
        elseif action.action == 'press' then
            if n.t == 'dropdown' and type(action.option) == 'number' and n.items[action.option+1] then
                state.dd_open = nil
                send({t='select', id=n.id, index=action.option, value=n.items[action.option+1]})
                request_render()
            elseif n.t == 'textbox' then focus_textbox(n)
            elseif n.click then send_click(n)
            elseif n.t == 'checkbox' then send({t='change', id=n.id, value=not n.value})
            elseif n.t == 'dropdown' then
                state.dd_open = n.id; state.dd_scroll = 0; request_render()
            end
        elseif (action.action == 'increment' or action.action == 'decrement') and n.t == 'slider' then
            local step = n.step or ((n.max or 1)-(n.min or 0))/100
            local value = clamp((n.value or n.min or 0) + (action.action == 'increment' and step or -step), n.min or 0, n.max or 1)
            send({t='change', id=n.id, value=value})
            send({t='commit', id=n.id, value=value})
        end
    end)
end)()
