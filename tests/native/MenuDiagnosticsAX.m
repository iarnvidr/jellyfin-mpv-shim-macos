#import <Cocoa/Cocoa.h>
#import <ApplicationServices/ApplicationServices.h>

static NSString *text(AXUIElementRef element, CFStringRef key) {
    CFTypeRef value = NULL;
    if (AXUIElementCopyAttributeValue(element, key, &value) != kAXErrorSuccess) return @"";
    id object = CFBridgingRelease(value);
    return [object isKindOfClass:NSString.class] ? object : @"";
}

static BOOL pressCopy(AXUIElementRef element, int depth) {
    if (depth > 12) return NO;
    if ([text(element, CFSTR("AXIdentifier")) isEqualToString:@"copy-diagnostics"]) {
        AXError result = AXUIElementPerformAction(element, kAXPressAction);
        printf("{\"copyAXResult\":%d}\n", result);
        return result == kAXErrorSuccess;
    }
    CFTypeRef children = NULL;
    if (AXUIElementCopyAttributeValue(element, kAXChildrenAttribute, &children) == kAXErrorSuccess) {
        for (id child in CFBridgingRelease(children)) {
            if (pressCopy((__bridge AXUIElementRef)child, depth + 1)) return YES;
        }
    }
    return NO;
}

int main(int argc, char **argv) {
    @autoreleasepool {
        if (argc != 3 || !AXIsProcessTrusted()) return 2;
        AXUIElementRef root = AXUIElementCreateApplication(atoi(argv[2]));
        BOOL success = NO;
        if (strcmp(argv[1], "copy") == 0) success = pressCopy(root, 0);
        else if (strcmp(argv[1], "close") == 0) {
            CFTypeRef windows = NULL;
            if (AXUIElementCopyAttributeValue(root, kAXWindowsAttribute, &windows) == kAXErrorSuccess) {
                for (id item in CFBridgingRelease(windows)) {
                    AXUIElementRef window = (__bridge AXUIElementRef)item;
                    if (![text(window, kAXTitleAttribute) isEqualToString:@"Jellyfin Player Settings"]) continue;
                    CFTypeRef button = NULL;
                    if (AXUIElementCopyAttributeValue(window, kAXCloseButtonAttribute, &button) == kAXErrorSuccess) {
                        AXError result = AXUIElementPerformAction((AXUIElementRef)button, kAXPressAction);
                        CFRelease(button);
                        printf("{\"closeAXResult\":%d}\n", result);
                        success = result == kAXErrorSuccess;
                    }
                }
            }
        }
        CFRelease(root);
        return success ? 0 : 1;
    }
}
