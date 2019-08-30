### Path Reconstruction
Two different versions of a program for the local and global reconstruction of muon tracks are provided. The details on how to use each one are below:

### 1. path_reconstruction_timens.ipynb

This version should run directly on the output of the current version of process_hits.py, which has each line of the file formatted as follows:

  event number,# of hits,< SL, LAYER, X_POS_LEFT, X_POS_RIGHT, TIMENS for each hit>
  
### 2. path_reconstruction_timens_jitter.ipynb

This version is the same as above but it allows you to adjust for a jitter in the trigger signal and has slightly different default parameters, including the approximate jitter I found for Run 617. However, it is likely more efficient to adjust for a jitter in the processing stage so I recommend using this version to just calibrate parameters and primarily use the version below for plotting, etc.
  
### 3. path_reconstruction_zpos.ipynb

This version runs on a differently formatted input,so it requires you to modify your processing program so that each line of its output is formatted as follows:

  event number,# of hits,orbit count for the event, < SL, LAYER, X_POS_LEFT, X_POS_RIGHT, ZPOS for each hit> 
  
I recommend using this version and output for the processing file because the calculation for ZPOS does not need to be repeated and orbit count is used as a marker for the events,which is unambigous, whereas event number varies based on the selection of data processed.

### Running path_reconstruction
To use either version,simply put the appropriate file path into local_reconstruction_xleft_xright('insert file path here') and adjust the parameters/plot outputs to your choosing
  
There are several different parameters that determine acceptance cuts for local/global reconstruction that can be found at the beginning of the file and you may find it appropriate to adjust them. Details on each one are provided in comments next to the values I have set as defaults.

By default the programs will not output any plots but you have the option to display local reconstructions, 2d plane reconstructions,3d global reconstructions, or a combination of the three. Instructions on how to activate the plots you would like to be displayed are in the comments at the end of the program. 

Note that if you are using jupyter notebook, local reconstructions and the option 'plot3d' do not work together,the comments have further details on how to get around this.

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
  
Note: process_hits.py has been updated since I wrote this,so you will likely find it more convenient to just run the updated process_hits and path_reconstruction programs separately.

Please let me know if you find any issues or have any questions! You can reach me by email at aidanf@mit.edu
