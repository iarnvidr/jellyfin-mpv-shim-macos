-- Run inside bundled mpv on macOS, or with a Lua interpreter in the container.
local engine = mp
local function verify()
    local callbacks, timers, properties, events = {}, {}, {}, {}
    mp = {
        register_script_message=function(name, callback) callbacks[name] = callback end,
        add_periodic_timer=function(_, callback) timers[#timers+1] = callback end,
        set_property_native=function(name, value) properties[name] = value end,
    }
    -- JSON is opaque to this unit harness; the packaged smoke also exercises
    -- the actual JSON/IPC and AppKit path.
    utils = {format_json=function(value) return value end, parse_json=function(value) return value end}
    state = {scene={}, nodes={}, byid={}, tb={}, w=800, h=600, dd={}}
    function tb_state(node)
        local value = state.tb[node.id]
        if not value then value={text=node.text or '', cursor=#(node.text or '')}; state.tb[node.id]=value end
        return value
    end
    function tb_changed(node, value) events[#events+1] = {id=node.id, value=value.text} end
    function focused_node() return state.byid[state.focus] end
    function tb_key(operation) events[#events+1] = {operation=operation} end
    function tb_fix_shift() end
    function request_render() end
    function compute_geo() end
    function modal_active() return state.modal end
    function visible(node) return not node.hidden end
    function eff(node) return node.x, node.y end
    function dd_state(node) return {sel=node.sel or 0} end
    function focus_textbox(node) state.focus=node.id end
    function nav_set(node) state.nav=node.id end
    function send(event) events[#events+1] = event end
    function send_click(node) send({t='click', id=node.id}) end
    function clamp(value, low, high) return math.max(low, math.min(high, value)) end
    local function node(id, kind, extra)
        local value = {id=id,t=kind,x=10,y=20,w=200,h=40}
        for key, item in pairs(extra or {}) do value[key]=item end
        state.nodes[#state.nodes+1] = value
        state.byid[id] = value
        return value
    end
    local text = node('search','textbox',{text='Monk', ph='Search'})
    node('password','textbox',{text='never-export-this', mask=true, ph='Password'})
    node('play','button',{click=true, text='Play Monk'})
    node('disabled','button',{click=true, dis=true})
    node('hidden','button',{click=true, hidden=true})
    node('volume','slider',{value=99,min=0,max=100,step=5})
    node('tracks','dropdown',{items={'English','Danish'},sel=0})
    dofile('work/NativeControls.lua')
    state.focus = text.id
    timers[1]()
    local tb = tb_state(text)
    tb.text, tb.cursor = 'Monk!', 5
    tb_changed(text,tb)
    timers[1]()
    assert(properties['user-data/jellyfin-native-edit'].undo)
    callbacks['jellyfin-native-edit']('UNDO')
    assert(tb.text == 'Monk' and tb.cursor == 4)
    timers[1]()
    assert(properties['user-data/jellyfin-native-edit'].redo)
    callbacks['jellyfin-native-edit']('REDO')
    assert(tb.text == 'Monk!')
    callbacks['jellyfin-native-edit']('SHOME')
    assert(tb.cursor == 0 and tb.sel == 5)
    timers[1]()
    assert(properties['user-data/jellyfin-native-edit'].selection)
    local model = properties['user-data/jellyfin-accessibility']
    local generation = model.nodes[1].generation
    for _, value in ipairs(model.nodes) do
        assert(value.id ~= 'hidden')
        if value.id == 'password' then
            assert(value.secure and value.value == '' and value.label == 'Password')
        end
    end
    local action = callbacks['jellyfin-accessibility-action']
    local count = #events
    action({id='disabled', action='press', generation=generation})
    assert(#events == count)
    action({id='play', action='press', generation=generation})
    assert(events[#events].id == 'play' and events[#events].t == 'click')
    action({id='volume', action='increment', generation=generation})
    assert(events[#events].t == 'commit' and events[#events].value == 100)
    action({id='tracks', action='press', generation=generation})
    timers[1]()
    action({id='tracks:option:2', control='tracks', option=1, action='press', generation=generation})
    assert(events[#events].t == 'select' and events[#events].value == 'Danish')
    state.scene = {}
    count = #events
    action({id='play', action='press', generation=generation})
    assert(#events == count, 'An action escaped into a newer scene')
    timers[1]()
    state.modal = true
    action({id='play', action='press', generation=generation+1})
    assert(#events == count, 'An action escaped behind a modal')
    print('Renderer: Undo/Redo, selection, password protection, activation, sliders, dropdowns and stale/modal action rejection passed')
end
local ok, error = pcall(verify)
mp = engine
if not ok then print(error) end
if engine then engine.commandv('quit', ok and 0 or 1) else assert(ok, error) end
