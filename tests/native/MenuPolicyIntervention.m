// Diagnostic-only, explicitly requested AFTER a reproduced passive failure.
// No constructor; mutations occur only through explicitly named test calls.
// No presentation/fullscreen writes or activation calls.
#import <Cocoa/Cocoa.h>
#import <stdatomic.h>
static _Atomic int result = -1;
__attribute__((visibility("default"))) void menuProofRequestRegular(void) {
    dispatch_async(dispatch_get_main_queue(), ^{
        atomic_store(&result, [NSApp setActivationPolicy:NSApplicationActivationPolicyRegular] ? 1 : 0);
    });
}
__attribute__((visibility("default"))) int menuProofPolicyResult(void) { return atomic_load(&result); }
__attribute__((visibility("default"))) void menuProofReassignCurrentMenu(void) {
    dispatch_async(dispatch_get_main_queue(), ^{ NSApp.mainMenu = NSApp.mainMenu; });
}
__attribute__((visibility("default"))) void menuProofCopyCurrentMenu(void) {
    dispatch_async(dispatch_get_main_queue(), ^{ NSApp.mainMenu = [NSApp.mainMenu copy]; });
}
__attribute__((visibility("default"))) void menuProofReassertZeroPresentation(void) {
    dispatch_async(dispatch_get_main_queue(), ^{
        if (NSApp.presentationOptions != 0) { atomic_store(&result, 0); return; }
        NSApp.presentationOptions = NSApp.presentationOptions;
        atomic_store(&result, 1);
    });
}
__attribute__((visibility("default"))) void menuProofSetMenuBarVisible(void) {
    dispatch_async(dispatch_get_main_queue(), ^{ [NSMenu setMenuBarVisible:YES]; });
}
