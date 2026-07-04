# Minimal self-contained screens so the project opens without the full GUI template.

define FONT = "fonts/PlayfairDisplay-Regular.ttf"

# Bottom narration window (per-scene narration).
screen say(who, what):
    style_prefix "say"
    window:
        id "window"
        vbox:
            spacing 8
            if who is not None:
                text who id "who"
            text what id "what"

# Centered narration, used for the opening intro over the title screen.
# Uses the truecenter transform (same as the title) for reliable centering.
screen centered_say(who, what):
    text what id "what" style "centered_text" at truecenter

screen choice(items):
    style_prefix "choice"
    vbox:
        xalign 0.5
        yalign 0.75
        spacing 16
        for i in items:
            textbutton i.caption action i.action

# "Press Start" gate shown after the title; only the button advances.
screen start_prompt():
    modal True
    add Solid("#000000")
    vbox:
        align (0.5, 0.5)
        spacing 44
        text "This is an interactive video.\nClick Start to begin — your choices shape the story." style "centered_text"
        textbutton "Start" action Return(True) style "start_button" xalign 0.5

style window:
    xfill True
    yalign 1.0
    ypadding 28
    xpadding 80
    background "#000000c0"

style say_who:
    font FONT
    color "#f0c674"
    size 30
    bold True

style say_what:
    font FONT
    color "#ffffff"
    size 30

style centered_text:
    font FONT
    color "#ffffff"
    size 42
    text_align 0.5
    xmaximum 1000
    line_spacing 8
    outlines [(2, "#000000", 0, 0)]

style choice_button:
    xalign 0.5

style choice_button_text:
    font FONT
    color "#ffffff"
    hover_color "#f0c674"
    size 30

style start_button:
    xalign 0.5
    padding (44, 18)
    background "#1a1a1aee"
    hover_background "#3a3a3aee"

style start_button_text:
    font FONT
    color "#ffffff"
    hover_color "#f0c674"
    size 34
