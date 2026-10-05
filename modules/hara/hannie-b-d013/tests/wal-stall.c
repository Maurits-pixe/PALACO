#define _GNU_SOURCE
#define _LARGEFILE64_SOURCE
#include <dlfcn.h>
#include <fcntl.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>
#include <errno.h>
#include <signal.h>

static long long milliseconds(void) {
  struct timespec ts; clock_gettime(CLOCK_REALTIME, &ts);
  return (long long)ts.tv_sec * 1000 + ts.tv_nsec / 1000000;
}
static void pause_if_armed(int fd) {
  const char *target = getenv("B013_WAL_PATH"), *arm = getenv("B013_WAL_ARM"), *trace = getenv("B013_NATIVE_TRACE");
  if (!target || !arm || !trace) return;
  char link[64], actual[PATH_MAX];
  snprintf(link, sizeof(link), "/proc/self/fd/%d", fd);
  ssize_t n = readlink(link, actual, sizeof(actual) - 1);
  if (n < 0) return;
  actual[n] = '\0';
  if (strcmp(actual, target) != 0 || unlink(arm) != 0) return;
  const char *mode = getenv("B013_NATIVE_MODE");
  if (mode && strcmp(mode, "kill-before-wal-write") == 0) {
    int out = open(trace, O_WRONLY | O_CREAT | O_APPEND, 0600);
    if (out >= 0) {
      const char record[] = "{\"kind\":\"NATIVE_COMMIT_INTERRUPT\",\"beforeWalWrite\":true}\n";
      ssize_t written = write(out, record, sizeof(record) - 1);
      close(out);
      if (written != (ssize_t)(sizeof(record) - 1)) _exit(91);
    }
    kill(getpid(), SIGKILL);
    _exit(92);
  }
  const long delay = 900;
  const long long start = milliseconds();
  struct timespec req = { delay / 1000, (delay % 1000) * 1000000 };
  while (nanosleep(&req, &req) != 0 && errno == EINTR) {}
  int out = open(trace, O_WRONLY | O_CREAT | O_APPEND, 0600);
  if (out >= 0) {
    char buf[256];
    int len = snprintf(buf, sizeof(buf), "{\"kind\":\"WAL_STALL\",\"pathConfirmed\":true,\"delayMs\":2400,\"startMs\":%lld,\"endMs\":%lld}\n", start, milliseconds());
    ssize_t written = write(out, buf, (size_t)len);
    close(out);
    if (written != len) return;
  }
}
ssize_t pwrite64(int fd, const void *buf, size_t count, off64_t offset) {
  static ssize_t (*real_fn)(int, const void *, size_t, off64_t);
  if (!real_fn) real_fn = dlsym(RTLD_NEXT, "pwrite64");
  pause_if_armed(fd);
  return real_fn(fd, buf, count, offset);
}
ssize_t pwrite(int fd, const void *buf, size_t count, off_t offset) {
  static ssize_t (*real_fn)(int, const void *, size_t, off_t);
  if (!real_fn) real_fn = dlsym(RTLD_NEXT, "pwrite");
  pause_if_armed(fd);
  return real_fn(fd, buf, count, offset);
}
