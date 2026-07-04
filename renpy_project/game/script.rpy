# Auto-generated interactive video script. Do not edit by hand.
define narrator = Character(None)
define intro_narrator = Character(None, screen="centered_say")
define mc = Character("Sam Chen")
image black = Solid("#000000")

label main_menu:
    jump start

label start:
    scene black with fade
    play sound "audio/title_sfx.ogg"
    show text "{font=fonts/PlayfairDisplay-Regular.ttf}{size=110}Same Pay, Different Pain{/size}{/font}" at truecenter with dissolve
    pause 2.5
    hide text with dissolve
    call screen start_prompt
    play sound "voice/intro_0.ogg"
    intro_narrator "Sam Chen is a 23-year-old physics dropout with equations in their notebook and rent due tomorrow."
    play sound "voice/intro_1.ogg"
    intro_narrator "They’ve got two job offers that pay the same but demand different kinds of pain—both buried in data, both drowning in chaos."
    play sound "voice/intro_2.ogg"
    intro_narrator "One path builds pipelines, the other builds models—but either way, entropy wins unless you fight it."
    play sound "voice/intro_3.ogg"
    intro_narrator "Your choices decide how Sam fights back."
    jump s1

label s1:
    $ renpy.movie_cutscene("movies/s1.webm")
    jump s2

label s2:
    $ renpy.movie_cutscene("movies/s2.webm")
    menu:
        "DATA ENGINEER":
            jump eng1
        "DATA SCIENTIST":
            jump sci1

label eng1:
    $ renpy.movie_cutscene("movies/eng1.webm")
    jump eng2

label eng2:
    $ renpy.movie_cutscene("movies/eng2.webm")
    jump eng3

label eng3:
    $ renpy.movie_cutscene("movies/eng3.webm")
    menu:
        "HOTFIX IT":
            jump eng4a
        "FIX IT RIGHT":
            jump eng4b

label eng4a:
    $ renpy.movie_cutscene("movies/eng4a.webm")
    jump end1

label eng4b:
    $ renpy.movie_cutscene("movies/eng4b.webm")
    jump end1

label sci1:
    $ renpy.movie_cutscene("movies/sci1.webm")
    jump sci2

label sci2:
    $ renpy.movie_cutscene("movies/sci2.webm")
    jump sci3

label sci3:
    $ renpy.movie_cutscene("movies/sci3.webm")
    menu:
        "SHIP IT":
            jump sci4a
        "TELL THE TRUTH":
            jump sci4b

label sci4a:
    $ renpy.movie_cutscene("movies/sci4a.webm")
    jump end1

label sci4b:
    $ renpy.movie_cutscene("movies/sci4b.webm")
    jump end1

label end1:
    $ renpy.movie_cutscene("movies/end1.webm")
    jump the_end

label the_end:
    narrator "The End."
    menu:
        "Play again":
            jump start
        "Quit":
            $ renpy.quit()
