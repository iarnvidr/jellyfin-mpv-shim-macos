#import "../../work/NativeScroll.m"

void JellyfinInstallNativeMenus(void) {}
void JellyfinClosePlayerWindow(void) {}

int main(void) {
    @autoreleasepool {
        [NSApplication sharedApplication];
        [NSApp setActivationPolicy:NSApplicationActivationPolicyAccessory];
        NSWindow *window = [[NSWindow alloc] initWithContentRect:NSMakeRect(100,100,800,600)
            styleMask:NSWindowStyleMaskTitled backing:NSBackingStoreBuffered defer:NO];
        [window makeKeyAndOrderFront:nil];
        NSDictionary *password = @{@"id": @"password", @"role": @"text", @"label": @"Password",
            @"value": @"", @"secure": @YES, @"enabled": @YES, @"focused": @YES,
            @"x": @20, @"y": @40, @"w": @300, @"h": @40, @"generation": @1};
        NSDictionary *button = @{@"id": @"play", @"role": @"button", @"label": @"Play Monk",
            @"enabled": @NO, @"x": @20, @"y": @100, @"w": @200, @"h": @40, @"generation": @1};
        updateAccessibility(@{@"w": @800, @"h": @600, @"nodes": @[password, button]});
        NSCAssert(accessibilityView.accessibilityChildren.count == 2, @"Native accessibility children missing");
        JellyfinAXElement *field = accessibilityView.elements[0];
        NSCAssert([field.accessibilityRole isEqual:NSAccessibilityTextFieldRole], @"Wrong text role");
        NSCAssert([field.accessibilitySubrole isEqual:NSAccessibilitySecureTextFieldSubrole], @"Password is not protected");
        NSCAssert([field.accessibilityValue isEqual:@""], @"Password data escaped");
        NSCAssert(field.accessibilityFrame.size.width == 300, @"Scene coordinates were not converted");
        NSCAssert(field.isAccessibilityFocused, @"Text focus missing");
        JellyfinAXElement *play = accessibilityView.elements[1];
        NSCAssert(!play.isAccessibilityEnabled && ![play accessibilityPerformPress], @"Disabled action was allowed");
        NSCAssert(![play isAccessibilitySelectorAllowed:@selector(setAccessibilityValue:)], @"Button became editable");
        updateAccessibility(@{@"w": @800, @"h": @600, @"nodes": @[password]});
        NSCAssert(accessibilityView.elements[0] == field, @"Unchanged controls lost their AX identity");
        NSCAssert(accessibilityView.elements.count == 1, @"Removed control is still exposed");
        NSLog(@"Native accessibility: roles, secure fields, coordinates, focus, disabled actions and stable identity passed");
    }
    return 0;
}
