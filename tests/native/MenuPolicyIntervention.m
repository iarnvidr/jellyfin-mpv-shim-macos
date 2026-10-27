// Diagnostic-only, explicitly requested AFTER a reproduced passive failure.
// No constructor, presentation writes, activation calls, or menu mutation.
#import <Cocoa/Cocoa.h>
#import <stdatomic.h>
static _Atomic int result = -1;
__attribute__((visibility("default"))) void menuProofRequestRegular(void) {
    dispatch_async(dispatch_get_main_queue(), ^{
        atomic_store(&result, [NSApp setActivationPolicy:NSApplicationActivationPolicyRegular] ? 1 : 0);
    });
}
__attribute__((visibility("default"))) int menuProofPolicyResult(void) { return atomic_load(&result); }
