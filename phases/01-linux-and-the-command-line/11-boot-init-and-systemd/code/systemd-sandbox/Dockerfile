# A throwaway box that boots systemd as PID 1, for the Use It half of lesson 11
# (and the capstone). The main sandbox (make shell) cannot run systemd: a normal
# container is a process, not a booted machine. This one is started privileged so
# that systemd can manage cgroups; use it only for the lessons, never for anything
# you would not run as root on your own laptop.
#
#   docker build -t phase1-systemd phases/01-linux-and-the-command-line/11-boot-init-and-systemd/code/systemd-sandbox
#   docker run -d --rm --privileged --name sysd \
#       -v "$PWD":/workspace:ro --tmpfs /run --tmpfs /run/lock phase1-systemd
#   docker exec -it sysd bash          # then: systemctl, journalctl, timers, cron, logrotate
#   docker stop sysd                    # when done
FROM debian:13-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
      systemd systemd-sysv cron logrotate python3 procps less curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*
STOPSIGNAL SIGRTMIN+3
CMD ["/sbin/init"]
