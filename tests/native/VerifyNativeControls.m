#import "../../work/NativeScroll.m"

void JellyfinInstallNativeMenus(void) {}
static BOOL closeRequested;
void JellyfinClosePlayerWindow(void) { closeRequested = YES; }

int main(void) {
    @autoreleasepool {
        [NSApplication sharedApplication];
        [NSApp setActivationPolicy:NSApplicationActivationPolicyAccessory];
        for (NSNumber *down in @[@YES, @NO]) {
            CGEventRef mouse = CGEventCreateMouseEvent(NULL, down.boolValue ? kCGEventLeftMouseDown : kCGEventLeftMouseUp,
                CGPointMake(140, 180), kCGMouseButtonLeft);
            CGEventSetFlags(mouse, kCGEventFlagMaskControl);
            NSEvent *original = [NSEvent eventWithCGEvent:mouse];
            NSEvent *context = browserControlClick(original);
            NSCAssert(context.type == (down.boolValue ? NSEventTypeRightMouseDown : NSEventTypeRightMouseUp), @"Control-click has the wrong event type");
            NSCAssert(context.buttonNumber == 1, @"Control-click still reaches mpv as a left button");
            NSCAssert(!(context.modifierFlags & NSEventModifierFlagControl), @"Control-click still has the Control modifier");
            NSCAssert(NSEqualPoints(original.locationInWindow, context.locationInWindow), @"Control-click changed target coordinates");
            CFRelease(mouse);
        }
        suppressEngineNowPlaying();
        MPNowPlayingInfoCenter.defaultCenter.nowPlayingInfo = @{MPMediaItemPropertyTitle: @"mpv"};
        MPNowPlayingInfoCenter.defaultCenter.playbackState = MPNowPlayingPlaybackStatePlaying;
        NSCAssert(MPNowPlayingInfoCenter.defaultCenter.nowPlayingInfo == nil, @"The engine is still publishing its own media card");
        NSCAssert(MPNowPlayingInfoCenter.defaultCenter.playbackState == MPNowPlayingPlaybackStateStopped, @"The engine reclaimed media playback ownership");
        NSWindow *window = [[NSWindow alloc] initWithContentRect:NSMakeRect(100,100,800,600)
            styleMask:(NSWindowStyleMaskTitled | NSWindowStyleMaskClosable) backing:NSBackingStoreBuffered defer:NO];
        [window makeKeyAndOrderFront:nil];
        applyPlayerBranding();
        NSRect originalFrame = window.frame;
        fillPlayerWindow(window);
        NSCAssert(sameFrame(window.frame, window.screen.visibleFrame), @"Zoom did not fill the usable desktop");
        fillPlayerWindow(window);
        NSCAssert(sameFrame(window.frame, originalFrame), @"Zoom did not restore the original frame");
        [[window standardWindowButton:NSWindowCloseButton] performClick:nil];
        NSCAssert(closeRequested && window.isVisible, @"Red close button bypassed the core stop/close handler");
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
