from nautobot.apps.jobs import Job, StringVar, BooleanVar, register_jobs

class SimpleInputJob(Job):
    """Echo a text input; optionally log extra debug info."""

    text_input = StringVar(
        label="Text Input",
        description="Enter some text to display",
        required=True,
    )

    show_debug = BooleanVar(
        label="Show Debug",
        description="Enable extra debug logging",
        default=False,
    )

    class Meta:
        name = "Simple Input Job"
        description = "Echo the text input with optional debug logs"

    def run(self, text_input, show_debug):
        # Always log the main message at INFO
        self.logger.info(f"You entered: {text_input}")

        # Only log extra details when requested
        if show_debug:
            self.logger.debug("Debug mode enabled")
            self.logger.debug(f"Length of input: {len(text_input)}")
            self.logger.debug(f"Uppercase input: {text_input.upper()}")

        # Prefer SUCCESS if available (>= 2.4.0), fall back to INFO
        success = getattr(self.logger, "success", None)
        if callable(success):
            self.logger.success("Job completed successfully")
        else:
            self.logger.info("Job completed successfully")

        return f"Job finished. Input was: {text_input}"

register_jobs(SimpleInputJob)
