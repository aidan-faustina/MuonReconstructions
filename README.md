### PathReconstruction
PathReconstruction is a program that will create local and global reconstructions of events in the muon chamber

To use,simply put the desired file path into local_reconstruction_xleft_xright(<your file name here>) and make sure that each line of the input file is formatted as follows (same as output for original process_hits.py):
  event number,hits,< SL, LAYER, X_POS_LEFT, X_POS_RIGHT, TIMENS for each hit> 

Further instructions on how to customize the output are written in comments at the end,above the relevant functions

### process_hits_v2.py
process_hits_v2.py is a version of the original process_hits that does the processing and reconstruction simultaneously. It outputs both local and global reconstructions of each acceptable event in .png file format as well as a text file in the same format as the original with TIMENS replaced by Z_POS to avoid repead calculations in reconstruction. 

To run process_hits_v2.py, add it into your miniDT folder and replace the existing confing file with the one I have provided. I have added a few new parameters so the program will NOT run without the new config file.

### Running process_hits_v2.py
   * using raw external trigger:  
     `./process_hits_v2.py -re <list of input TXT files>` (Currently NOT working)
   * using raw external trigger, with `t0` determined by meantimer (for avoiding jitter of the external trigger):  
     `./process_hits_v2.py -ura <list of input TXT files>`
   * using meantimer to find aligned hits in each orbit (external trigger not used at all):
     `./process_hits_v2.py -tra <list of input TXT files>`
     I recommend using the parameters below as well, otherwise a lot of plots will be output and it will run quite slowly
   * to only process a certain subset of the events add --range start end
   * to plot a certain subset of reconstructions together on one figure use -j start end

NOTE: both programs currently only reconstruct the BEST fit for any given event, meaning that even if an event has more than one muon,only ONE track is reconstructed. I am currently testing ways to reconstruct all paths in an event without sacrificing quality. 

Please let me know if you find any issues or have any questions!
