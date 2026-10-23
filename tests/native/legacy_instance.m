// Test fixture: legacy lock/wire protocol with a real hidden/minimized AppKit
// window. It deliberately acknowledges SHOW before restoring the window.
#import <Cocoa/Cocoa.h>
#import <arpa/inet.h>
#import <fcntl.h>
#import <sys/file.h>
#import <sys/socket.h>
#import <unistd.h>

int main(int argc, char **argv) {
    @autoreleasepool {
        if (argc != 4) return 2;
        NSString *directory = @(argv[1]);
        NSString *mode = @(argv[2]);
        NSString *ready = @(argv[3]);
        NSString *endpoint = [directory stringByAppendingPathComponent:@"instance.lock"];
        int guard = open([[endpoint stringByAppendingString:@".guard"] fileSystemRepresentation], O_CREAT|O_RDWR, 0600);
        if (guard < 0 || flock(guard, LOCK_EX|LOCK_NB) != 0) return 3;
        int listener = socket(AF_INET, SOCK_STREAM, 0);
        struct sockaddr_in address = {0};
        address.sin_len = sizeof(address);
        address.sin_family = AF_INET;
        address.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
        if (bind(listener, (struct sockaddr *)&address, sizeof(address)) != 0 || listen(listener, 5) != 0) return 4;
        socklen_t size = sizeof(address);
        getsockname(listener, (struct sockaddr *)&address, &size);
        NSString *token = @"0123456789abcdef0123456789abcdef";
        NSString *data = [NSString stringWithFormat:@"%d\n%@\n", ntohs(address.sin_port), token];
        [data writeToFile:endpoint atomically:YES encoding:NSUTF8StringEncoding error:nil];
        NSApplication *app = NSApplication.sharedApplication;
        [app setActivationPolicy:NSApplicationActivationPolicyRegular];
        NSWindow *window = [[NSWindow alloc] initWithContentRect:NSMakeRect(100,100,480,320) styleMask:NSWindowStyleMaskTitled|NSWindowStyleMaskMiniaturizable backing:NSBackingStoreBuffered defer:NO];
        window.title = @"Legacy Jellyfin MPV Shim test fixture";
        [window makeKeyAndOrderFront:nil];
        dispatch_async(dispatch_get_global_queue(QOS_CLASS_USER_INITIATED, 0), ^{
            for (;;) {
                int client = accept(listener, NULL, NULL);
                if (client < 0) break;
                char buffer[64] = {0};
                ssize_t count = read(client, buffer, sizeof(buffer)-1);
                NSString *request = count > 0 ? [[NSString alloc] initWithBytes:buffer length:count encoding:NSUTF8StringEncoding] : @"";
                if ([request isEqualToString:[NSString stringWithFormat:@"JMS1%@\n", token]]) {
                    write(client, "JMS1OK", 6);
                    dispatch_async(dispatch_get_main_queue(), ^{
                        [app unhide:nil];
                        [window deminiaturize:nil];
                        [window makeKeyAndOrderFront:nil];
                    });
                }
                close(client);
            }
        });
        dispatch_after(dispatch_time(DISPATCH_TIME_NOW, NSEC_PER_SEC), dispatch_get_main_queue(), ^{
            if ([mode isEqualToString:@"minimized"]) [window miniaturize:nil];
            else [app hide:nil];
            [@"ready" writeToFile:ready atomically:YES encoding:NSUTF8StringEncoding error:nil];
        });
        [app run];
        close(listener);
        close(guard);
    }
    return 0;
}
