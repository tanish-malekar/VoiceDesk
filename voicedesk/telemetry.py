"""Log content-free server state latency proxies and SDK component metrics."""
import logging
import time

logger = logging.getLogger("voicedesk.latency")


class TurnClock:
    def __init__(self, clock=time.perf_counter):
        self.clock = clock
        self.last_user_stop = None

    def user_state(self, old, new):
        if new == "speaking":
            self.last_user_stop = None
        elif old == "speaking" and new == "listening":
            self.last_user_stop = self.clock()

    def agent_state(self, new):
        if new != "speaking" or self.last_user_stop is None:
            return None
        elapsed_ms = (self.clock() - self.last_user_stop) * 1000
        self.last_user_stop = None
        return elapsed_ms


def attach_telemetry(session):
    clock = TurnClock()

    @session.on("user_state_changed")
    def user_changed(event):
        clock.user_state(event.old_state, event.new_state)

    @session.on("agent_state_changed")
    def agent_changed(event):
        elapsed_ms = clock.agent_state(event.new_state)
        if elapsed_ms is not None:
            logger.info("user_stop_to_agent_speaking_proxy_ms=%.1f", elapsed_ms)

    @session.on("metrics_collected")
    def collected(event):
        metric = event.metrics
        # Never serialize complete events or conversational content.
        values = {key: getattr(metric, key) for key in ("duration", "ttft", "ttfb", "end_of_utterance_delay")
                  if isinstance(getattr(metric, key, None), (int, float))}
        logger.info("component=%s timings_seconds=%s", metric.type, values)
