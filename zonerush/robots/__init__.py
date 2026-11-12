"""Robots for Round 2: the physical robots act out the moves the engine has already decided.

The engine's board is official (4.3). A robot never decides anything: it only runs the simple
steps the server sends it, and the server only sends steps for moves the engine has resolved
and approved (a "move" event). A blocked move, STAY or SHIELD never makes a robot move.

    protocol.py   the text messages between server and robot, and RobotClient (one robot)
    links.py      how the messages travel: Bluetooth (BLE), USB serial, or a simulated robot
    planner.py    "seat 2 moved NORTH" -> robot steps ("turn left, forward one cell")
    fleet.py      all the robots of a game: connect, act out each turn, handle faults
    camera.py     the overhead camera check: is every robot where the server says?
    markers.py    printable ArUco markers: one per seat, plus four board corners
"""
