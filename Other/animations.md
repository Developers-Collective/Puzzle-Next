# Using changed/new animations

## Original animations
If you got a tileset with changed original animations, e.g. for the ?-Block, you can simply follow a tutorial on how to add that tileset to your game.

## New animations
New animations only work for mods based on [NewerSMBW](https://newerteam.com/wii/). In this case you should already have an existing AnimTiles.bin file from a folder called `...\NewerRes` and also have gotten a new AnimTiles.bin file aside from the tileset containing the framesheets of the new animations.
You will have to add both the tileset and the AnimTiles.bin file to the game (mod). For the tileset you can simply follow a tutorial on how to add that tileset to your game.

### Add a complete AnimTiles.bin  file
If not otherwise stated it is to be expected that the AnimTiles.bin file you got contains both all the animation entries for the newly added animations as well as all the animations from NewerSMBW.
If you haven't added any other animations to your own AnimTiles.bin file previously you can simply replace your one.

Otherwise you have to import the new AnimTiles.bin file in the "AnimTiles" tab of [Puzzle Next](https://github.com/N-I-N-0/Puzzle-Next) and copy the entries with matching framesheet names.
If you open the tileset the new animations belong to besides the AnimTiles.bin you can simply import the new animations belonging to the particular tileset from the "AnimTiles" tab into the "Animation Editor".
Afterwards you have to go to the "AnimTiles" tab and open the old AnimTiles.bin and then at last export from the "Animation Editor" into the newly opened file in the "AnimTiles" tab. There you export to a new AnimTiles.bin file that you can then use to replace your old one with.

### Add an incomplete AnimTiles.bin file
If you know that the AnimTiles.bin file you got only contains the newly added animations, simply open it and copy the text in the "AnimTiles" tab of Puzzle Next. Now you open your old AnimTiles.bin file and add the copied text to it. Now export to a new AnimTiles.bin file and replace your old one.

### What is a AnimTiles.txt file
A AnimTiles.txt file contains the text you can see after opening a AnimTiles.bin file in the "AnimTiles" tab of Puzzle Next. They are mostly used for incomplete AnimTiles information to simplify the process of integrating them into an already existing AnimTiles.bin



# Creating animations

## Needed program
[Puzzle Next](https://github.com/N-I-N-0/Puzzle-Next) - recommended at least

## Original animations (e.g. ?-Block -> hatena_anime)
If you want to change animations the original game already had - such as the ?-Block - you can just replace the picture of the animation in the tileset containing the original animation, safe the tileset and add it to your game.

## New animations
If you plan to create new tileset animations you have to know that they only will work with mods based on [NewerSMBW](https://newerteam.com/wii/).
That is the case because you not only will have to create the framesheet containing the new animation but also a so called AnimTiles.bin file.
A AnimTiles.bin file contains information about the framedelays and even more importantly: for which tile of the tileset the animation is to be played.
After adding a new framesheet to a tileset in the "Framesheets" tab you can click on it and then go to the "Animation Editor". In this tab you can edit the animation and after finishing export it to the "AnimTiles" tab. Once you are there you can simply export to a .bin file.
Since you will have to use a NewerSMBW based mod for this to work out to begin with, you might want to first import the existing AnimTiles.bin file and then export your animation from the "Animation Editor" to the "AnimTiles" tab as to not loose other animations. 

## More information on the formats
[Horizon wiki](https://horizon.miraheze.org/wiki/Animated_Tiles)
