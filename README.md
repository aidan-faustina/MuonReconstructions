PathReconstruction is a program that will create local and global reconstructions of events in the muon chamber

To use,simply put the desired file path into local_reconstruction_xleft_xright(<your file name here>) and make sure that each line of the input file is formatted as follows (same as output for original process_hits.py):
  event number,hits,< SL, LAYER, X_POS_LEFT, X_POS_RIGHT, TIMENS for each hit> 

Further instructions on how to customize the output are written in comments at the end,above the relevant functions

A modified version of process_hits.py which processes hits and outputs plots as .png files all in one will be posted here soon

Please let me know if you find any issues or have any questions!
