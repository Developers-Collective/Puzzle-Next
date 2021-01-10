# Using tilesets

## ... in the game on an actual Wii
If you want to use a tileset on the Wii you have to use [Riivolution](https://rvlution.net/wiki/Riivolution/). There are lots of tutorials on how to install Riivolution using the Homebrew Channel out there.

The easiest way to get your tilesets in the game now is using [NewerSMBW](https://newerteam.com/wii/) and replace tilesets in the folder `\NewerSMBW\Tilestes`.
This way you won't get them into the original game but since you are into modding using NewerSMBW to start of might actually be what you want to do anyway.

Another way to get a tileset into the game is by creating a new .xml file following these pages (works for both mods and the original game - might conflict with mods sometimes though): 
[Patch Format](https://rvlution.net/wiki/Patch_Format/),
[Patch Templates](https://rvlution.net/wiki/Patch_Templates/)

## ... in the game on a PC (Dolphin Emulator)
If you already have the game on your PC it is recommended to first extract it and then play it by starting the main.dol from the sys folder.
You can find a tutorial on the [Horizon wiki](https://horizon.miraheze.org/wiki/Dolphin_Emulator#No-ISO_Method_.28Extracted_Game.29)

After you have extracted the game you can go to the folder `\DATA\files\Stage\Texture` and replace the original tilesets.
Make sure that the slot of the new tileset matches with the old one. This can usally be seen from the number in the name of the tileset (e.g. Pa**0**...) or instead in the [Puzzle Next](https://github.com/N-I-N-0/Puzzle-Next) tileset editor.

## ... in Reggie Next (level editor)
If you already got the Reggie Next level editor and set it up correctly you can now go to the `\Texture` folder in your stage folder and replace or add new tilesets. If you added a new tileset you have to add a new entry to the `tilesets.xml` of the reggie game patch. Also don't forget to add every new tilesets to your game later as well!
