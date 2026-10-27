// Disposable CI read-only AX inspection; no preference selection/writes.
#import <Cocoa/Cocoa.h>
#import <ApplicationServices/ApplicationServices.h>
static NSString *value(AXUIElementRef node, CFStringRef key) {
    CFTypeRef raw = NULL;
    if (AXUIElementCopyAttributeValue(node, key, &raw)) return @"";
    id object = CFBridgingRelease(raw);
    return [object isKindOfClass:NSString.class] ? object : @"";
}
static void collect(AXUIElementRef node, NSMutableArray *nodes, int depth) {
    if (depth > 40 || nodes.count > 10000) return;
    [nodes addObject:(__bridge id)node]; CFTypeRef raw = NULL;
    if (AXUIElementCopyAttributeValue(node, kAXChildrenAttribute, &raw)) return;
    for (id child in CFBridgingRelease(raw)) collect((__bridge AXUIElementRef)child, nodes, depth + 1);
}
int main(void) {
    @autoreleasepool {
        [NSApplication sharedApplication]; [NSApp setActivationPolicy:NSApplicationActivationPolicyAccessory];
        NSMutableArray *panes = [NSMutableArray array];
        NSString *directory = @"/System/Library/ExtensionKit/Extensions";
        for (NSString *entry in [NSFileManager.defaultManager contentsOfDirectoryAtPath:directory error:nil]) {
            if (![entry.lowercaseString containsString:@"menubar"] && ![entry.lowercaseString containsString:@"menu-bar"]) continue;
            NSString *identifier = [NSBundle bundleWithPath:[directory stringByAppendingPathComponent:entry]].bundleIdentifier;
            if (identifier) [panes addObject:identifier];
        }
        NSArray *choices = @[@"Always", @"Never", @"In Full Screen Only", @"On Desktop Only"];
        NSDictionary *result = @{@"status": @"unavailable", @"panes": panes};
        for (NSString *pane in panes) {
            [NSWorkspace.sharedWorkspace openURL:[NSURL URLWithString:[@"x-apple.systempreferences:" stringByAppendingString:pane]]];
            NSDate *until = [NSDate dateWithTimeIntervalSinceNow:8];
            while (until.timeIntervalSinceNow > 0) {
                [NSRunLoop.currentRunLoop runUntilDate:[NSDate dateWithTimeIntervalSinceNow:.5]];
                NSRunningApplication *app = [NSRunningApplication runningApplicationsWithBundleIdentifier:@"com.apple.systempreferences"].firstObject;
                if (!app) continue;
                AXUIElementRef root = AXUIElementCreateApplication(app.processIdentifier);
                NSMutableArray *nodes = [NSMutableArray array]; collect(root, nodes, 0); CFRelease(root);
                for (id object in nodes) {
                    AXUIElementRef node = (__bridge AXUIElementRef)object;
                    if (![value(node, kAXRoleAttribute) isEqualToString:@"AXPopUpButton"]) continue;
                    NSString *selected = value(node, kAXValueAttribute);
                    if (![choices containsObject:selected]) continue;
                    result = @{@"status": @"read", @"selected": selected, @"pane": pane,
                               @"title": value(node, kAXTitleAttribute), @"description": value(node, kAXDescriptionAttribute)};
                    goto done;
                }
            }
        }
    done: ;
        NSData *data = [NSJSONSerialization dataWithJSONObject:result options:NSJSONWritingSortedKeys error:nil];
        [NSFileHandle.fileHandleWithStandardOutput writeData:data];
        return 0;
    }
}
