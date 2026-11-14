# Keepy Upy punch list

Last updated: 13 November 2026

## Done

**Confirmed by you**
- [x] Both robots (Cozmo and MiP) connect at the same time
- [x] Voice commands work for the robots
- [x] AR tape plan for the arena (live tape view on the camera)
- [x] Two games in scope: keepy uppy and floor soccer (2 people vs 2 robots, air-hockey style)

**Built and tested in simulation**
- [x] Balloon tracking: floor spot and height from the ceiling camera (yellow colour, AI backup)
- [x] Robot tags printed at the right size: Cozmo 4 cm (tag 1), MiP 5 cm (tag 2)
- [x] Robots stay inside the play area. Soccer (10 Nov rule): robots may cross the
      centre line and go up to halfway into the people's half, never the half by the
      people's goal. People stay behind their own goal line, outside the arena, and reach
      in to hit or tap the balloon with their hands and arms (13 Nov; harder than the
      robots push).
- [x] Soccer scorekeeper: goals, "Out!", score, serve rules
  - Nobody kicks: people hit or tap the balloon with their hands and arms from behind
    their goal line, robots push it with their bodies
  - New game: people serve toward the robots
  - After a goal: the team that scored serves from their side
  - After "Out!": the team whose side it went out on serves
  - The first goal wins the game (13 Nov; was first to 5)
  - Stuck (13 Nov): a balloon that doesn't move for 10 seconds (somewhere nobody can
    reach) is served again by the team whose side it's on
  - Goal: counts as soon as the balloon, rolling on the floor from inside the arena,
    touches the pink goal line between the two pink posts (decided 12-13 Nov). Coming back
    in through the goal, or a serve put down on the line, doesn't count.
- [x] Robots guard and attack in strips: the arena is cut in two the long way. Cozmo
      has the back strip and guards the back half of the goal, MiP the front. When the
      balloon is in a robot's strip and within reach, it pushes it at the people's goal.
      In simulation they never get closer than 19 cm.

## Taping and setup

1. [x] Arena taped: purple border all the way round, pink centre line and goal marks.
       Camera repositioned so all four corners are in view.
2. [x] All tape done for both games and checked against the plan on camera (8 Nov):
       purple border and corner crosses, pink centre line, pink goal lines and posts,
       blue keepy uppy rest squares (back corners), pink soccer robot squares by the
       robots' goal. The pink centre line doubles as the keepy uppy middle line.
3. [x] Arena measured: width 10'-0" (corner 1 to 2), depth 5'-4" (corner 1 to 4).
       On camera these don't quite fit together (picture ratio 1.78, measured 1.88).
       Optional: re-measure the depth at both ends, and the width along top and
       bottom, to the middle of the purple tape. Fits within about 3 cm: good enough.
       Re-measuring checked off by you (12 Nov): after the floor map was re-saved the
       worst corner is about 5 cm off, well inside the robots' 20 cm safety zone.
4. [x] Floor map saved with the measured size (8 Nov), lined up with the taped corners.
       Code matches the tape, measured on camera: goals 72 cm, blue rest squares
       42 cm, pink soccer squares 30 cm, 6 cm in from the border.
       Checks re-run on the real arena: tape tracking 12/12, scorekeeper 7/7,
       balloon maths and robot steering all pass.
5. [x] Camera lens measured at 6'-6" (1.98 m) above the floor; ceiling is 6'-10.25"
       (2.09 m). Floor map re-saved with the camera height; the lens works out to
       about 82 degrees wide. All checks still pass.
6. [x] Balloon measured on camera: 32.7 cm (about 13 in), saved. Resting on the floor
       it reads 16 cm high (correct; it read 0 before). Fixed: the tracker now sends
       the balloon size to the robot program, which had always assumed 36 cm.
7. [x] Goal width decided: keep 72 cm, as taped (8 Nov). For reference, the
       simulation on the real arena with the real balloon (150 shots, robots
       guarding) gave 72 cm 0 goals, 85 cm 23, 1 m 35. Check in real games
       (step 22) whether people can score; widen if not.
8. [x] Flag on MiP (pink). Cozmo's flag, if wanted.
9. [x] Flags work with both robots so far (8 Nov). Keep an eye out during robot
       testing: no sticky residue, nothing blocking wheels, lift, sensors or MiP's
       balance, and light enough not to tip them.
10. [x] Test the AprilTags: the camera can see both, but 4–5 cm tags are too small to
        read reliably from the ceiling (read in only 1–14% of pictures).
11. [x] Switched to coloured tape on top: green patch on each robot, pink front piece
        on Cozmo, blue on MiP. The live tracker found Cozmo in 98% and MiP in 100% of
        pictures. Green things outside the arena are ignored.
        A robot hidden under the balloon keeps its last spot for 2 s and holds still.
12. [x] Make the pink and blue front pieces bigger (about 3 cm) so the facing direction
        is reliable. Checked off by you (12 Nov).
13. [x] Yellow tennis ball moved out of the camera's view (it looked like the balloon).
14. [x] Check the tracker sees the balloon everywhere in the play area. Checked off by
        you (12 Nov). Seen in every
        reading in the middle of the arena (8 Nov); still to check the corners, the
        edges and up in the air.
15. [x] Step stool moved out of the arena.

## Then: robot testing (robots are paused until you say go)

16. [ ] Keepy uppy dry run (no robots move): `python chase.py --dry-run`
17. [ ] Keepy uppy with the real robots, low speed, one robot at a time, then both.
        Check they turn the right way.
18. [x] Robots bumping in soccer: fixed with strips (see 19) and a keep-apart rule:
        within 35 cm the robot not going for the balloon won't drive toward the other;
        within 20 cm neither does. In simulation never closer than 19 cm.
19. [~] Soccer with the real robots: double-click "Keepy Up Soccer" on the Desktop.
        Done so far:
        - MiP alone, live (8 Nov, about 18 min): the whole game worked (serves, outs,
          goals), people 1 - robots 2.
        - Strips (10 Nov): Cozmo back, MiP front, each from the robots' goal up to the
          halfway limit on the people's side; neither enters the other's strip.
          Simulated (150 serves): 37 robot goals, never closer than 19 cm, never past
          the limit or out of the arena.
        - Both robots inside the border: targets stay inside the 20 cm safety zone and
          they slow down near the border.
        - Same speed: both top out at 0.20 m/s, Cozmo's fastest (12 Nov; was 0.18).
        - Cozmo: cliff stop is off (it locked his wheels on the first try, 10 Nov; the
          floor is flat and the camera keeps him inside the tape). Green patch re-stuck,
          seen 100% of the time.
        - Robot sounds (11 Nov): quiet reactions in their own voices to Play, Out, goals,
          wins and a new game. Cozmo only animates when play has stopped.
        - Game screen (11 Nov): remembers the last robots, checklist, checks Cozmo's
          Wi-Fi, big score, what each robot is doing, MiP's battery, p pause, q stop,
          summary with "play again". Voice "start" / "stop" (see 23). If the screen
          closes, the robots stop.
        - Logs in keepy-up/logs/ (robots, camera, scoreboard), with each robot's
          status and the time.
        - First real test, both robots (11 Nov evening): failed. MiP crept backwards
          instead of going for the balloon (the slow speed setting was too weak for it;
          battery 11% in the first game). MiP's Bluetooth dropped twice, which stopped
          the whole robot program and lost Cozmo, and Cozmo then wouldn't reconnect
          off his charger. MiP also left balloons in Cozmo's strip while Cozmo was out.
        - Fixed (12 Nov), tested with pretend robots and the simulation (unchanged:
          37 robot goals, strips never crossed):
          1. MiP rolls firmly (speed dial 18 or more) in short hops with pauses, so
             on average it still goes at Cozmo's speed.
          2. MiP's Bluetooth drops no longer stop the game: it reconnects by itself
             and Cozmo keeps playing.
          3. [removed 12 Nov] "Out of play": the other robot covered for one that
             dropped out. In the 10:22 pm game it kept flipping both robots in and
             out (Cozmo was never really on), so it was taken out again.
          4. Cozmo starts ON his charger; once connected the screen says to move him
             into his pink square, and the robots wait for Return or "start".
          5. Red warning on the game screen when MiP's battery is under 25%.
        - Second real test (11 Nov, 10:22 pm): still not working. Cozmo connected but
          never moved: he reports factory/recovery firmware, so only his Wi-Fi chip
          answers (wheels, face and lights stay off). MiP lined up behind the balloon
          but hung back 30-40 cm and rarely pushed it, and wandered to the front edge.
        - Back to basics (12 Nov): rules restored to before 11 Nov evening; kept MiP's
          firm rolls, Bluetooth reconnect, Cozmo charger step and battery warning.
        - MiP-only test (11 Nov, 10:39 pm, about 3 min, home Wi-Fi): worked. MiP stayed
          on the balloon (touching or within a few cm), pushed it across the centre
          line, and the robots scored (People 0 - 1 Robots). Camera never lost MiP, no
          Bluetooth drops, never over the tape. Battery 62% -> 55%. To improve: pushes
          are gentle, and once it took ~13 s lining up behind the balloon.
        - Clean-up (12 Nov): removed code nothing used: an unused stop command, the
          Cozmo cliff-stop option (Cozmo's own cliff stop is still switched off), the
          animations switch and the old keepy uppy animation list.
        Still to do:
        a. [x] MiP only, on home Wi-Fi: goes after the balloon at 0.20 m/s (11 Nov, 10:39 pm).
        e. [x] Cozmo: connect him once with the official Cozmo app so it updates his
           firmware (PyCozmo's author: Cozmo falls back to factory firmware after a
           communication error). Then check he drives before he joins a game.
           Note: the Mac's Cozmo app has firmware 2457; PyCozmo was tested with 2381.
           Done 12 Nov: updated with the Cozmo app. Cozmo-only game (7:48 pm, about
           3.5 min): no recovery-firmware warning, and he chased and pushed the balloon
           the whole time (often so close the balloon hid him from the camera).
        f. [x] Cozmo's new face, expressions, arm and idle sounds (see 20): all worked
           in the 8:00 pm Cozmo-only game (about 5 min, no errors, he drove the whole
           time; People 2 - 0 Robots), at about MiP's volume.
           Open question: at 8:03 pm the people scored 1 s after the robots' serve.
           Was the balloon put down by the goal, or did Cozmo push it in himself?
        g. [x] Both robots together (12-13 Nov):
           - 8:15 pm: never got to "Play!": MiP's Bluetooth dropped 7 times in about a
             minute (each time it reconnected by itself). Not caused by Cozmo's face:
             a face picture is at most 55 bytes.
           - 8:23 pm: two game windows were open; both heard "start" and ran two robot
             programs, which fought over Cozmo, and no scoreboard started. MiP's
             Bluetooth dropped about 8 times in 80 s; Cozmo mostly waited ("too close")
             because a frozen MiP stood next to him.
           - Fixed (12 Nov): only one game window can run at a time (a second one says
             so and closes), and the scoreboard check no longer mistakes a game window
             for the scoreboard. Tested with pretend robots.
           - 8:48 pm: one window and the scoreboard ran, but MiP's Bluetooth dropped
             twice in 25 s before "Play!". Drops got this bad only once Cozmo worked
             properly: the Mac uses one radio for Cozmo's Wi-Fi and MiP's Bluetooth.
           - Fixed (12 Nov), tested with pretend robots: Cozmo's wheel commands are only
             sent when they change (less Wi-Fi traffic); MiP isn't hung up on over one
             failed command (only when the link is down or 3 fail in a row), and the log
             says which kind of drop it was; a reconnecting (frozen) robot has no right
             of way, so the other doesn't wait behind it.
           - 13 Nov, 7:38 pm: WORKED. Cozmo and MiP played a whole game together (about
             5.5 min). MiP's Bluetooth dropped 4 times and reconnected by itself each time
             (was 7-8 a minute before the radio fixes). Goals both ways, sounds played.
           - Changed after that game (13 Nov), tested with pretend balloons, the simulation
             (still never closer than 19 cm, never in the other's strip) and a pretend game:
             a robot whose strip doesn't have the balloon stops where it is instead of
             driving back to its pink square (it went back and forth a lot); robots go back
             to their squares only at a serve or when the balloon is out of reach. And a
             goal only counts when the balloon rolls in from inside the arena: at 7:42 one
             counted as it was brought back in through the goal, and at 7:43 a serve put
             down on the line scored at once.
           Still to do: a live game to try these two changes.
        b. [x] MiP's Bluetooth drops: reconnects by itself (12 Nov, fix 2). Check it
           live.
        c. [x] "Out!" was too jumpy (6 calls in 40 s with the balloon on the edge tape).
           Fixed 12 Nov: only called once the balloon has been outside for 0.5 s. Tested
           with pretend balloons and a scripted pretend game.
        d. Check MiP's sound numbers by ear (Go 29, Yesss 81, Awww 15).
20. [x] Add Cozmo's reactions. Soccer done (hello, goals, wins; see 19).
        Personality (12 Nov, soccer): his normal blinking eyes are back on; expressions
        for 1.5 s at moments without an animation (happy at Play and new game,
        surprised at Out, sad when the people score); a small arm raise with happy
        moments and idle sounds (arm down while driving); a quiet idle sound (hum,
        giggle or vroom) every 15-25 s while he plays. Volume matched to MiP's share
        (MiP 2 of 7, Cozmo 18,724 of 65,535; was 15,000). Worked live (12 Nov, 8:00 pm).
        Chase sound (12 Nov): a quiet "vroom" or excited sound with an arm lift when
        he sets off after the balloon, at most every 10 s; idle sounds wait while he
        chases. About 6 arm lifts a minute instead of 4. Tested with a pretend Cozmo.
        Goodnight at the end: not needed (you, 13 Nov). Keepy uppy reactions: checked off by
        you (12 Nov).
21. [x] MiP behaviours. Soccer sounds done (see 19). Keepy uppy: checked off by you (12 Nov).
22. [ ] Test both games end to end with people playing: keepy uppy, then floor soccer
        with the scoreboard.
23. [x] Voice commands in the games. Soccer done (11 Nov): say "start" to start
        (menu, checklist, end screen; also carries on after a pause) and "stop" to stop
        the game. Offline (Vosk, same voice model as the voice app), listens for those two
        words only, nothing saved. Tested with recorded speech and a pretend microphone;
        not yet with a real voice in the room. Keepy uppy: checked off by you (12 Nov).

## Final step: sound

24. [x] Add sound effects (the robots' own voices, quietly; see 28). Checked off by you
        (12 Nov):
    - [x] Start sequence before every game, first or new (12 Nov): "Get ready..." on the
          scoreboard, then big green 1, 2, 3 (a beep each, one second apart,
          sounds/count.wav) just below the team names in the game window and in place of
          "Play!" on the scoreboard, then START! with the start sound. The robots and the
          scoreboard are held until START! (also MiP only, and after a reconnect).
    - [x] New game (12 Nov): n in the game window starts a new game (0 - 0, the start
          sequence, the same sounds as the first game). The scoreboard window ignores the
          keyboard when the game window starts it: typing while it was in front had pressed
          R (new game) and space (pause). After a win it says "Press n in the game window".
    - [x] Wording (12 Nov): "Robot's balloon" and "People's balloon" instead of "serve".
          Scripted pretend game with two games (9:36 pm): the second game played every
          sound in order. The first game's scoreboard said "Play!" about 40 s late, so its
          goals didn't count; not seen again in two re-runs. Watch for it in real games.
    - [x] Game started (soccer: "Go!")
    - [x] Goal scored (soccer)
    - [x] A team wins (soccer)
    - [x] Balloon falls to the floor (keepy uppy): checked off by you (12 Nov)
    - [x] Soccer sound effects on the Mac's speakers (12 Nov; Angry Birds clips you
          chose, in keepy-up/sounds/; home use only, keep them off the website):
          start (robots released, and "play again"), every goal, the win (on the winning
          goal: goal sound, then win sound), near miss (the balloon's
          middle within 30 cm of a goal line between the posts, then away without a goal;
          the screen says "So close!"), a robot's missed push (pushed 1 s or more, balloon
          moved under 5 cm), and game stopped (q, "stop" or Ctrl+C). Near miss and missed
          push at most every 5 s. stop.wav is the same clip as miss.wav (swap the file to
          change it). All clips are quiet. Scripted pretend game (12 Nov, 9:05 pm): all 7
          played in order at the right moments (start, miss, near miss, goal x4, goal +
          win, stop). Not yet heard in a real game.
    - [x] Out sound (12 Nov, sounds/out.wav): plays once for each "Out!"; nearly in and
          then out beside a post plays the near-miss sound, then the out sound. Scripted
          pretend game with two games (9:54 pm): every sound in order in both games.

## Open decisions

25. [x] Goal width: keep 72 cm as taped; revisit after real games (see 7).
26. [x] After "Out!": the team whose side the balloon went out on serves.
27. [x] How a soccer game is won: the first goal wins (13 Nov; was first to 5). n in the
        game window starts a new game.
28. [x] Sounds: the robots' own voices, quietly (11 Nov). Soccer done (see 19).
29. [x] Safety: people and children aren't tracked. Checked off by you (12 Nov): a
        grown-up keeps watching, and speeds stay low.

## Elsewhere

30. [ ] Website (handled in the other chat): document everything on this list, including
        both games and their rules, the tape layout, tags and flags, robot guarding, the
        punch list itself, and the planned sounds. Keep it updated as items get done.

## Ideas for later

31. [x] Cancelled by you (12 Nov). Robot cameras. MiP has no camera; its chest sensor senses hands and objects
        about 10-30 cm ahead, which could become a "something in front, stop" check.
        Cozmo has a small camera, kept off for now: the ceiling camera already sees
        everything, and Cozmo's sits at child eye level. If used: balloon only,
        nothing saved.
