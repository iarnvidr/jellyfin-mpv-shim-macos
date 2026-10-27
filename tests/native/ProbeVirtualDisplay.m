#import <Cocoa/Cocoa.h>
#import <CoreGraphics/CoreGraphics.h>

// Private CoreGraphics interfaces also used by Chromium's display tests:
// https://chromium.googlesource.com/chromium/src/+/HEAD/ui/display/mac/test/virtual_display_util_mac.mm
// This is a disposable-runner capability probe, never application code.
@interface CGVirtualDisplayDescriptor : NSObject
@property(nonatomic, strong) dispatch_queue_t queue;
@property(nonatomic, copy) NSString *name;
@property(nonatomic) CGSize sizeInMillimeters;
@property(nonatomic) unsigned int maxPixelsWide, maxPixelsHigh;
@property(nonatomic) CGPoint redPrimary, greenPrimary, bluePrimary, whitePoint;
@property(nonatomic) unsigned int serialNum, productID, vendorID, serialNumber;
@end
@interface CGVirtualDisplayMode : NSObject
- (instancetype)initWithWidth:(unsigned int)width height:(unsigned int)height refreshRate:(double)rate;
@end
@interface CGVirtualDisplaySettings : NSObject
@property(nonatomic) unsigned int hiDPI, rotation;
@property(nonatomic, copy) NSArray *modes;
@end
@interface CGVirtualDisplay : NSObject
@property(nonatomic, readonly) unsigned int displayID;
- (instancetype)initWithDescriptor:(CGVirtualDisplayDescriptor *)descriptor;
- (BOOL)applySettings:(CGVirtualDisplaySettings *)settings;
@end

static CGVirtualDisplay *virtualDisplay;
static CGVirtualDisplay *upperDisplay;
static NSString *outputDirectory;

static CGVirtualDisplay *createDisplay(unsigned int width, unsigned int height, BOOL retina, unsigned int serial) {
    CGVirtualDisplayDescriptor *descriptor = [[NSClassFromString(@"CGVirtualDisplayDescriptor") alloc] init];
    descriptor.queue = dispatch_get_global_queue(QOS_CLASS_USER_INITIATED, 0);
    descriptor.name = retina ? @"Jellyfin diagnostic Retina primary" : @"Jellyfin diagnostic upper external";
    descriptor.maxPixelsWide = width * (retina ? 2 : 1); descriptor.maxPixelsHigh = height * (retina ? 2 : 1);
    descriptor.sizeInMillimeters = CGSizeMake(345, 224);
    descriptor.whitePoint = CGPointMake(.3125, .3291);
    descriptor.redPrimary = CGPointMake(.6797, .3203);
    descriptor.greenPrimary = CGPointMake(.2559, .6983);
    descriptor.bluePrimary = CGPointMake(.1494, .0557);
    descriptor.vendorID = 505; descriptor.productID = retina ? 101 : 102;
    descriptor.serialNum = serial;
    if ([descriptor respondsToSelector:@selector(setSerialNumber:)]) descriptor.serialNumber = serial;
    CGVirtualDisplay *display = [[NSClassFromString(@"CGVirtualDisplay") alloc] initWithDescriptor:descriptor];
    CGVirtualDisplaySettings *settings = [[NSClassFromString(@"CGVirtualDisplaySettings") alloc] init];
    settings.hiDPI = retina ? 1 : 0; settings.rotation = 0;
    settings.modes = @[[[NSClassFromString(@"CGVirtualDisplayMode") alloc] initWithWidth:width height:height refreshRate:60]];
    return display && [display applySettings:settings] ? display : nil;
}

static void emit(NSString *phase, NSDictionary *details) {
    uint32_t ids[32], count = 0;
    CGError status = CGGetOnlineDisplayList(32, ids, &count);
    NSMutableArray *displays = [NSMutableArray array], *screens = [NSMutableArray array];
    for (uint32_t index = 0; index < count; index++) {
        CGRect bounds = CGDisplayBounds(ids[index]);
        [displays addObject:@{@"id": @(ids[index]), @"model": @(CGDisplayModelNumber(ids[index])),
            @"builtin": @(CGDisplayIsBuiltin(ids[index])), @"main": @(CGDisplayIsMain(ids[index])),
            @"mirrorOf": @(CGDisplayMirrorsDisplay(ids[index])),
            @"bounds": NSStringFromRect(NSRectFromCGRect(bounds)),
            @"pixels": @[@(CGDisplayPixelsWide(ids[index])), @(CGDisplayPixelsHigh(ids[index]))]}];
    }
    BOOL hasScale2 = NO;
    for (NSScreen *screen in NSScreen.screens) {
        NSEdgeInsets safe = screen.safeAreaInsets;
        hasScale2 |= screen.backingScaleFactor == 2;
        [screens addObject:@{@"id": screen.deviceDescription[@"NSScreenNumber"] ?: @0,
            @"frame": NSStringFromRect(screen.frame), @"visibleFrame": NSStringFromRect(screen.visibleFrame),
            @"scale": @(screen.backingScaleFactor), @"safeArea": @[@(safe.top), @(safe.left), @(safe.bottom), @(safe.right)]}];
    }
    NSMutableDictionary *record = [@{@"phase": phase, @"time": @(NSDate.date.timeIntervalSince1970),
        @"onlineResult": @(status), @"onlineDisplayCount": @(count), @"displays": displays,
        @"screens": screens, @"virtualDisplayID": @(virtualDisplay.displayID),
        @"displaysHaveSeparateSpaces": @(NSScreen.screensHaveSeparateSpaces),
        @"qualifiedSecondHiDPI": @(status == kCGErrorSuccess && count >= 2 && screens.count >= 2 && hasScale2)} mutableCopy];
    [record addEntriesFromDictionary:details ?: @{}];
    NSData *json = [NSJSONSerialization dataWithJSONObject:record options:NSJSONWritingSortedKeys error:nil];
    [json writeToFile:[outputDirectory stringByAppendingPathComponent:[phase stringByAppendingString:@".json"]] atomically:YES];
    fwrite(json.bytes, 1, json.length, stdout); fputc('\n', stdout); fflush(stdout);
}

int main(int argc, const char **argv) {
    @autoreleasepool {
        if (argc < 2) return 2;
        outputDirectory = [NSString stringWithUTF8String:argv[1]];
        BOOL vertical = argc > 3 && strcmp(argv[3], "vertical") == 0;
        CGDirectDisplayID originalMain = CGMainDisplayID();
        [NSApplication sharedApplication];
        [NSApp setActivationPolicy:NSApplicationActivationPolicyAccessory];
        emit(@"before", nil);
        NSArray *classes = @[@"CGVirtualDisplay", @"CGVirtualDisplayDescriptor", @"CGVirtualDisplayMode", @"CGVirtualDisplaySettings"];
        for (NSString *name in classes) if (!NSClassFromString(name)) {
            emit(@"after", @{@"status": @"api-unavailable", @"missingClass": name}); return 0;
        }
        dispatch_after(dispatch_time(DISPATCH_TIME_NOW, NSEC_PER_SEC / 2), dispatch_get_main_queue(), ^{
            if (vertical) {
                virtualDisplay = createDisplay(1512, 982, YES, getpid());
                upperDisplay = createDisplay(1920, 1200, NO, getpid() + 1);
                emit(@"created", @{@"vertical": @YES});
                dispatch_after(dispatch_time(DISPATCH_TIME_NOW, 3 * NSEC_PER_SEC), dispatch_get_main_queue(), ^{
                    CGDisplayConfigRef configuration;
                    CGError arranged = kCGErrorFailure;
                    if (virtualDisplay && upperDisplay && CGBeginDisplayConfiguration(&configuration) == kCGErrorSuccess) {
                        CGError first = CGConfigureDisplayOrigin(configuration, virtualDisplay.displayID, 0, 0);
                        CGError second = CGConfigureDisplayOrigin(configuration, upperDisplay.displayID, -175, -1200);
                        CGError mirror = CGConfigureDisplayMirrorOfDisplay(configuration, originalMain, virtualDisplay.displayID);
                        arranged = CGCompleteDisplayConfiguration(configuration, kCGConfigureForSession);
                        emit(@"arranged", @{@"primaryOriginResult": @(first), @"upperOriginResult": @(second), @"originalMirrorResult": @(mirror)});
                    }
                    dispatch_after(dispatch_time(DISPATCH_TIME_NOW, 4 * NSEC_PER_SEC), dispatch_get_main_queue(), ^{
                        emit(@"after", @{@"vertical": @YES, @"arrangeResult": @(arranged), @"status": @"vertical-creation-attempted"});
                    });
                });
                return;
            }
            CGVirtualDisplayDescriptor *descriptor = [[NSClassFromString(@"CGVirtualDisplayDescriptor") alloc] init];
            descriptor.queue = dispatch_get_global_queue(QOS_CLASS_USER_INITIATED, 0);
            descriptor.name = @"Jellyfin diagnostic HiDPI";
            descriptor.maxPixelsWide = 3024; descriptor.maxPixelsHigh = 1964;
            descriptor.sizeInMillimeters = CGSizeMake(345, 224);
            descriptor.whitePoint = CGPointMake(.3125, .3291);
            descriptor.redPrimary = CGPointMake(.6797, .3203);
            descriptor.greenPrimary = CGPointMake(.2559, .6983);
            descriptor.bluePrimary = CGPointMake(.1494, .0557);
            descriptor.vendorID = 505; descriptor.productID = 100;
            descriptor.serialNum = getpid();
            if ([descriptor respondsToSelector:@selector(setSerialNumber:)]) descriptor.serialNumber = getpid();
            virtualDisplay = [[NSClassFromString(@"CGVirtualDisplay") alloc] initWithDescriptor:descriptor];
            CGVirtualDisplaySettings *settings = [[NSClassFromString(@"CGVirtualDisplaySettings") alloc] init];
            settings.hiDPI = 1; settings.rotation = 0;
            settings.modes = @[[[NSClassFromString(@"CGVirtualDisplayMode") alloc] initWithWidth:1512 height:982 refreshRate:60]];
            BOOL applied = virtualDisplay && [virtualDisplay applySettings:settings];
            emit(@"created", @{@"settingsApplied": @(applied)});
            dispatch_after(dispatch_time(DISPATCH_TIME_NOW, 3 * NSEC_PER_SEC), dispatch_get_main_queue(), ^{
                CGDisplayConfigRef configuration;
                CGError arranged = kCGErrorFailure;
                if (virtualDisplay.displayID && CGBeginDisplayConfiguration(&configuration) == kCGErrorSuccess) {
                    CGRect main = CGDisplayBounds(CGMainDisplayID());
                    CGConfigureDisplayMirrorOfDisplay(configuration, virtualDisplay.displayID, kCGNullDirectDisplay);
                    CGConfigureDisplayOrigin(configuration, virtualDisplay.displayID, CGRectGetMaxX(main), 0);
                    arranged = CGCompleteDisplayConfiguration(configuration, kCGConfigureForSession);
                }
                dispatch_after(dispatch_time(DISPATCH_TIME_NOW, 2 * NSEC_PER_SEC), dispatch_get_main_queue(), ^{
                    emit(@"after", @{@"settingsApplied": @(applied), @"arrangeResult": @(arranged),
                        @"status": virtualDisplay ? @"creation-attempted" : @"creation-unavailable"});
                });
            });
        });
        [NSTimer scheduledTimerWithTimeInterval:.2 repeats:YES block:^(NSTimer *timer) {
            if (virtualDisplay && [[NSFileManager defaultManager] fileExistsAtPath:[outputDirectory stringByAppendingPathComponent:@"remove-request"]]) {
                upperDisplay = nil; virtualDisplay = nil;
                dispatch_after(dispatch_time(DISPATCH_TIME_NOW, 2 * NSEC_PER_SEC), dispatch_get_main_queue(), ^{ emit(@"removed", nil); });
            }
        }];
        double duration = argc > 2 ? atof(argv[2]) : 30;
        dispatch_after(dispatch_time(DISPATCH_TIME_NOW, MIN(duration, 900) * NSEC_PER_SEC), dispatch_get_main_queue(), ^{
            upperDisplay = nil; virtualDisplay = nil; [NSApp terminate:nil];
        });
        [NSApp run];
    }
    return 0;
}
