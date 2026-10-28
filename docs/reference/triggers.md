# Trigger publication API

::: stateforge_provider.triggers

## Runtime boundary

`Provider.publish_trigger()` is the only callback entry point. The decorator,
receipt, outcome, rejection, and typed local errors above are safe public
values. The Provider runtime privately adapts them to P3 protobuf messages and
owns streaming, flow control, acknowledgement correlation, retry, and replay.
