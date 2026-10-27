// CI observation helper only: no activation/presentation setters, no titles/names.
#import <Cocoa/Cocoa.h>
#import <CoreGraphics/CoreGraphics.h>

static NSArray *rect(CGRect r) { return @[@(r.origin.x), @(r.origin.y), @(r.size.width), @(r.size.height)]; }
int main(void) {
    @autoreleasepool {
        uint32_t count = 0;
        if (CGGetActiveDisplayList(0, NULL, &count) != kCGErrorSuccess) return 1;
        CGDirectDisplayID displays[16];
        uint32_t found = 0;
        if (CGGetActiveDisplayList(16, displays, &found) != kCGErrorSuccess) return 1;
        NSArray *windows = CFBridgingRelease(CGWindowListCopyWindowInfo(kCGWindowListOptionOnScreenOnly, kCGNullWindowID));
        if (!windows) return 1;
        NSMutableArray *rows = [NSMutableArray array];
        int menuLevel = CGWindowLevelForKey(kCGMainMenuWindowLevelKey);
        int statusLevel = CGWindowLevelForKey(kCGStatusWindowLevelKey);
        for (uint32_t i = 0; i < found; i++) {
            CGRect bounds = CGDisplayBounds(displays[i]);
            CGRect band = CGRectMake(bounds.origin.x, bounds.origin.y, bounds.size.width, MIN(48, bounds.size.height));
            NSMutableArray *overlaps = [NSMutableArray array];
            NSUInteger omitted = 0;
            for (NSDictionary *window in windows) {
                CGRect frame;
                if (!CGRectMakeWithDictionaryRepresentation((__bridge CFDictionaryRef)window[(id)kCGWindowBounds], &frame)) continue;
                int level = [window[(id)kCGWindowLayer] intValue];
                if (level < 0 || !CGRectIntersectsRect(frame, band)) continue;
                if (overlaps.count >= 128) { omitted++; continue; }
                [overlaps addObject:@{@"ownerPID": window[(id)kCGWindowOwnerPID] ?: @0,
                    @"number": window[(id)kCGWindowNumber] ?: @0,
                    @"layer": @(level), @"bounds": rect(frame), @"alpha": window[(id)kCGWindowAlpha] ?: @0,
                    @"onScreen": @([window[(id)kCGWindowIsOnscreen] boolValue] ? 1 : 0),
                    @"menuLevelMatch": @(level == menuLevel ? 1 : 0),
                    @"statusLevelMatch": @(level == statusLevel ? 1 : 0)}];
            }
            [rows addObject:@{@"displayID": @(displays[i]), @"main": @(displays[i] == CGMainDisplayID() ? 1 : 0),
                @"builtin": @(CGDisplayIsBuiltin(displays[i]) ? 1 : 0), @"bounds": rect(bounds), @"menuBand": rect(band),
                @"overlappingWindows": overlaps, @"overlapsOmitted": @(omitted)}];
        }
        NSDictionary *report = @{@"wallTime": @(NSDate.date.timeIntervalSince1970),
            @"monotonic": @(NSProcessInfo.processInfo.systemUptime),
            @"activePID": @(NSWorkspace.sharedWorkspace.frontmostApplication.processIdentifier),
            @"separateSpaces": @(NSScreen.screensHaveSeparateSpaces ? 1 : 0),
            @"menuLevel": @(menuLevel), @"statusLevel": @(statusLevel),
            @"displays": rows, @"displaysOmitted": @(count > found ? count - found : 0)};
        NSData *data = [NSJSONSerialization dataWithJSONObject:report options:NSJSONWritingSortedKeys error:nil];
        if (!data || data.length > 262144) return 1;
        [NSFileHandle.fileHandleWithStandardOutput writeData:data];
        [NSFileHandle.fileHandleWithStandardOutput writeData:[@"\n" dataUsingEncoding:NSUTF8StringEncoding]];
    }
    return 0;
}
