class ProposalGuidance:
    @staticmethod
    def _build_next_actions(feature: str) -> list[str]:
        common = [
            "Keep the generated snippet formatted as a managed include snippet under klipperai/*.cfg.",
            "Review the current config for overlapping sections before adding this proposal.",
        ]
        feature_specific = {
            "fan": [
                "Replace the placeholder fan pin with the actual MCU output pin.",
                "Decide whether this should be [fan], [heater_fan], or [controller_fan].",
            ],
            "macro": [
                "Replace the macro body with the exact sequence you want Klipper to run.",
                "Choose a final macro name that matches your workflow.",
            ],
            "sensor": [
                "Replace the sensor type and sensor pin with the real hardware values.",
                "Confirm the expected safe temperature range for this sensor.",
            ],
            "probe": [
                "Replace the probe pin and real probe offsets.",
                "Confirm whether a specialized probe type like BLTouch needs a different section.",
            ],
            "heater": [
                "Confirm whether this should be a heater_fan, temperature_fan, or a different heater-related section.",
                "Replace the placeholder fan pin with the correct output pin.",
            ],
            "input_shaper": [
                "Replace the placeholder shaper frequencies with measured resonance values.",
                "Confirm whether you already have an accelerometer section configured.",
            ],
            "bed_mesh": [
                "Replace mesh bounds with reachable probe coordinates.",
                "Confirm the probe_count and speed fit your printer size and probe type.",
            ],
            "filament": [
                "Replace the switch pin with the actual runout sensor input.",
                "Decide whether you want pause-only behavior or custom runout macros.",
            ],
            "canbus": [
                "Replace the CAN UUID with the real toolhead board UUID.",
                "Confirm the MCU alias matches the rest of your config references.",
            ],
            "stepper": [
                "Replace driver pins and current values with board-specific values.",
                "Confirm the correct driver family before applying the section.",
            ],
            "extruder": [
                "Replace motion pins and calibrate rotation_distance.",
                "Confirm heater and sensor values if this is meant to become a full extruder section.",
            ],
            "generic": [
                "Rewrite the generic scaffold into the exact Klipper section you need.",
                "Ask a more specific follow-up for tighter config generation.",
            ],
        }
        return [*feature_specific.get(feature, feature_specific["generic"]), *common]

    @staticmethod
    def _build_follow_up_questions(feature: str) -> list[str]:
        questions = {
            "fan": [
                "Is this a part-cooling fan, hotend fan, controller fan, or chamber fan?",
                "What MCU pin is the fan connected to?",
            ],
            "macro": [
                "What should the macro do step by step?",
                "Do you want it to call existing Klipper macros or stand alone?",
            ],
            "sensor": [
                "What exact sensor hardware are you using?",
                "What pin is the sensor connected to?",
            ],
            "probe": [
                "What probe hardware are you using?",
                "Do you already know the probe offsets or should those remain placeholders?",
            ],
            "heater": [
                "Is this for a hotend cooling fan, chamber control, or another heater-linked behavior?",
                "What output pin should control it?",
            ],
            "input_shaper": [
                "Do you already have measured resonance frequencies?",
                "Is your accelerometer already configured in Klipper?",
            ],
            "bed_mesh": [
                "What are the safe probe bounds on your bed?",
                "What probe hardware are you using for bed mesh generation?",
            ],
            "filament": [
                "Is the sensor a simple switch or a motion sensor?",
                "Do you want pause behavior only or custom runout actions too?",
            ],
            "canbus": [
                "What CAN toolhead board are you using?",
                "Do you already know the CAN UUID and desired MCU alias?",
            ],
            "stepper": [
                "Which axis or motor are you tuning?",
                "What driver family are you using?",
            ],
            "extruder": [
                "Is this a full extruder section or just a tuning adjustment?",
                "Do you already know the calibrated rotation_distance?",
            ],
            "generic": [
                "Which exact printer feature do you want to configure?",
                "Do you want the proposal formatted as a managed include snippet under klipperai/*.cfg?",
            ],
        }
        return questions.get(feature, questions["generic"])
