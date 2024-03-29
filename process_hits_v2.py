#!/usr/bin/env python
from pdb import set_trace as br
from time import clock
from multiprocessing import Process
import math
import numpy as np
import pandas as pd
import itertools
import os 
import sys
import operator
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d import Axes3D
from matplotlib.backends.backend_pdf import PdfPages

# Importing custom code snippets
from modules.analysis.patterns import PATTERNS, PATTERN_NAMES, ACCEPTANCE_CHANNELS, MEAN_TZERO_DIFF, meantimereq, mean_tzero, tzero_clusters
from modules.analysis.config import NCHANNELS, XCELL, ZCELL, Z_SEP, TDRIFT, VDRIFT, CHANNELS_TRIGGER, CHANNEL_TRIGGER, EVENT_NR_CHANNELS
from modules.analysis.config import max_slope,chisq_local,chisq_2d,chisq_3d
from modules.analysis.config import EVENT_TIME_GAP, TIME_OFFSET, TIME_OFFSET_SL, TIME_WINDOW, DURATION, TRIGGER_TIME_ARRAY
from modules.analysis.config import NHITS_SL, MEANTIMER_ANGLES, MEANTIMER_CLUSTER_SIZE, MEANTIMER_SL_MULT_MIN
from modules.analysis.utils import print_progress, mem



############################################# INPUT ARGUMENTS 
import argparse
parser = argparse.ArgumentParser(description='Offline analysis of unpacked data. t0 id performed based on pattern matching.')
parser.add_argument('inputs', metavar='FILE', help='Unpacked input file to analyze', nargs='+')
parser.add_argument('-a', '--accepted',  help='Save only events that passed acceptance cuts', action='store_true', default=False)
parser.add_argument('-c', '--csv',  help='Print final selected hits into CSV files', action='store_true', default=False)
parser.add_argument('--chambers',  help='Minimum number of chambers with 1+ hits', action='store', default=4, type=int)
parser.add_argument('-d', '--double_hits',  help='Accept only events with 2+ hits in a cell', action='store_true', default=False)
parser.add_argument('-e', '--event',  help='Split hits in events based on event number', action='store_true', default=False)
parser.add_argument('-E', '--events', metavar='N',  help='Only process events with specified numbers', type=int, default=None, nargs='+')
parser.add_argument('-g', '--group', metavar='N', type=int, help='Process input files sequentially in groups of N', action='store', default=999999)
parser.add_argument('-l', '--layer',   action='store', default=None, dest='layer',   type=int, help='Layer to process [default: process all 4 layers]')
parser.add_argument('-m', '--max_hits',   action='store', default=200, dest='max_hits',   type=int, help='Maximum number of hits allowed in one event [default: 200]')
parser.add_argument('-n', '--number', action='store', default=None,  dest='number', type=int, help='Number of hits to analyze. (Note: this is applied to each file if multiple files are analyzed with -g)')
parser.add_argument('-r', '--root',  help='Print output to a ROOT friendly text file', action='store_true', default=False)
parser.add_argument('-s', '--suffix',  action='store', default=None, help='Suffix to add to output file names', type=str)
parser.add_argument('-t', '--triplets',  help='Do triplet search', action='store_true', default=False)
parser.add_argument('-u', '--update_tzero',  help='Update TIME0 with meantimer solution', action='store_true', default=False)
parser.add_argument('-v', '--verbose',  help='Increase verbosity of the log', action='store', default=0)
parser.add_argument('--range',  help='Specify a range of acceptable events to process', action='store', default=[0,None],nargs = 2)
parser.add_argument('-j','--join',  help='Specify a range of reconstructions to plot together on the same figure', action='store', default=[0,None],nargs = 2)
args = parser.parse_args()
for file_path in args.inputs:
    if not os.path.exists(os.path.expandvars(file_path)):
        print('--- ERROR ---')
        print('file not found')
        print('  please point to the correct path to the file containing the unpacked data' )
        print()
        exit()

VERBOSE = int(args.verbose)
EVT_COL = 'EVENT_NR' if args.event else 'ORBIT_CNT'

#                         / z-axis (beam direction)
#                        .
#                       .
#                  ///////////|   
#                 ///////////||
#                ||||||||||||||
#                ||||||||||||||  SL 1/3
#                ||||||||||||/
#                |||||||||||/
#  y-axis       .          .
#(vertical     .          .
# pointing    .          .
# upward)    .          .
#   ^       .          .           y-axis
#   |   ///////////|  .            ^ 
#   |  ///////////|| .             |  z-axis 
#   | ||||||||||||||.              | / 
#   | ||||||||||||||  SL 0/2       |/
#   | ||||||||||||/                +-------> x-axis 
#   | |||||||||||/                 
#   +-------------> x-axis (horizontal)


#    layer #             cell numbering scheme
#      1         |    1    |    5    |    9    |
#      2              |    3    |    7    |   11    |
#      3         |    2    |    6    |   10    |
#      4              |    4    |    8    |   12    |

def analyse_parallel(args):
    """Wrapper around the main function to properly pass arguments"""
    return analyse(*args)

############################################# ANALYSIS
def analyse(dfhits, SL):

    meantimer_info = {
        't0_diff': [],
        't0_mult': [],
        'triplet_angle': [],
        'nhits/event': [],
    }
    tzerodiff = []
    tzeromult = []
    hitperorbit = []

    # Selecting only physical channels of this layer
    sel = dfhits['TDC_CHANNEL_NORM'] <= NCHANNELS

    events = dfhits[sel].groupby('EVENT_NR')
    # # Excluding groups that have multiple time measurements with the same channel
    # # They strongly degrade performance of meantimer
    # idx = dfhits.loc[dfhits['TDC_CHANNEL_NORM'] <= NCHANNELS].groupby(EVT_COL).filter(lambda x: x['TDC_CHANNEL_NORM'].size == x['TDC_CHANNEL_NORM'].nunique()).index

    n_events = len(events)
    n_events_processed = 0

    print('### SL {0:d}: Starting analysis with {1:d} hits in {2:d} events'.format(SL, dfhits.shape[0], len(events)))
    if VERBOSE:
        nhits = events['TDC_CHANNEL'].size()
        print('Number of hits per event:  min: {0:d}   max: {1:d}'.format(nhits.min(), nhits.max()))
    for event, df in events:
        print_progress(n_events_processed, n_events, SL)
        n_events_processed += 1
        n_hits = df.shape[0]

        if VERBOSE > 1:
            print('analyzing event', event)
            print('# hits =', n_hits)

        meantimer_info['nhits/event'].append(n_hits)

        # Getting the TIME0
        tzero = df.iloc[0]['TIME0']
        tzeromult.append(1)

    # Selecting only hits that are from events with TIME0 properly estimated
    idx = dfhits['TIME0'] > 0
    
    # correct hits time for tzero
    dfhits.loc[idx, 'TIMENS'] = dfhits['TIME_ABS'] - dfhits['TIME0']
    
    # assign hits position (left/right wrt wire)

    dfhits.loc[idx, 'X_POS_LEFT']  = ((dfhits['TDC_CHANNEL_NORM']-0.5).floordiv(4) + dfhits['X_POSSHIFT'])*XCELL + XCELL/2 - np.maximum(dfhits['TIMENS'], 0)*VDRIFT
    dfhits.loc[idx, 'X_POS_RIGHT'] = ((dfhits['TDC_CHANNEL_NORM']-0.5).floordiv(4) + dfhits['X_POSSHIFT'])*XCELL + XCELL/2 + np.maximum(dfhits['TIMENS'], 0)*VDRIFT
    df = dfhits.loc[idx]

    # Returning the calculated results
    return (SL, dfhits, df, meantimer_info)


def event_nr(numbers):
    return (numbers.iloc[0] << 12) | (numbers.iloc[1] << 8) | (numbers.iloc[2] << 4) | (numbers.iloc[3])


def calc_event_numbers(allhits):
    """Calculates event number for groups of hits based on trigger hits"""
    # Creating a dataframe to be filled with hits from found events (for better performance)
    hits = allhits.loc[:1, ['EVENT_NR', 'TIME0']]
    # Selecting only hits containing information about the event number or trigger signals
    channels = EVENT_NR_CHANNELS + CHANNELS_TRIGGER
    sel = pd.Series(False, allhits.index)
    for ch in channels:
        sel = sel | ((allhits['FPGA'] == ch[0]) & (allhits['TDC_CHANNEL'] == ch[1]))
    # Selecting hits that have to be grouped by time
    ev_hits = allhits.loc[sel]
    print('### Grouping hits by their time of arrival')
    # Creating the list of hits with 1 on jump in time
    evt_group = (ev_hits['ORBIT_CNT'].astype(np.uint64)*DURATION['orbit:bx'] + ev_hits['BX_COUNTER']).sort_values().diff().fillna(0).astype(np.uint64)
    evt_group[evt_group <= EVENT_TIME_GAP] = 0
    evt_group[evt_group > EVENT_TIME_GAP] = 1
    # Calculating cumulative sum to create group ids
    evt_group = evt_group.cumsum()
    # Adding column to be used for grouping hits with event number and trigger
    allhits['evt_group'] = evt_group
    allhits['evt_group'] = allhits['evt_group'].fillna(-1).astype(int)
    # Getting back rows with relevant channels with grouping column updated
    ev_hits = allhits.loc[evt_group]
    ev_hits.set_index(['FPGA', 'TDC_CHANNEL'], inplace=True)
    # Checking each group to calculate event number for it
    evt_groups = ev_hits.groupby('evt_group')
    n_groups = len(evt_groups)
    n_groups_done = 0
    last_evt_id = -1
    # Creating a dataframe with 1 row per event
    df_events = pd.DataFrame(data={'EVENT_ID': list(evt_groups.groups.keys())})
    df_events['TIME0'] = -1
    df_events['EVENT_NR'] = -1
    df_events['TRG_BITS'] = -1
    df_events['TIMEDIFF_TRG_20'] = -1e9
    df_events['TIMEDIFF_TRG_21'] = -1e9
    df_events.set_index('EVENT_ID', inplace=True)
    df_events.sort_index(inplace=True)
    # Calculating event number for each group of hits
    for grp, df in evt_groups:
        print_progress(n_groups_done, n_groups)
        n_groups_done += 1
        df = df.sort_index()
        try:
            vals_int = df['TDC_MEAS'].reindex(EVENT_NR_CHANNELS, fill_value=0)
        except Exception:
            # Removing duplicate entries with the same channel value (very rare occasion)
            if VERBOSE:
                print('WARNING: duplicate entries with the same channel for event number:')
                print(df[['ORBIT_CNT', 'BX_COUNTER', 'TDC_MEAS']])
            df = df[~df.index.duplicated(keep='first')]
            vals_int = df['TDC_MEAS'].reindex(EVENT_NR_CHANNELS, fill_value=0)

        evt_id = event_nr(vals_int)
        # Skipping if only one specific event should be processed
        if args.events and evt_id not in args.events:
            continue

        # Check whether trigger signal is present
        if CHANNEL_TRIGGER not in df.index:
            print('WARNING: No trigger channel {0}'.format(CHANNEL_TRIGGER))
            print('         Event skipped')
            # Storing information about available trigger signals
            df_trg = df['TDC_MEAS'].reindex(CHANNELS_TRIGGER, fill_value=-111)
            # Packing bits into 8bit integer and shifting by 5 positions to the right
            trg_bits = np.packbits(df_trg != -111) >> 5
            df_events.loc[grp, ['EVENT_NR', 'TRG_BITS']] = (evt_id, trg_bits)
            if VERBOSE:
              print(allhits.loc[allhits["ORBIT_CNT"].isin(range(orbit_event-10,orbit_event+10))].loc[allhits["TDC_CHANNEL"].isin(channels)])
            continue

        # Getting time and orbit number of the event after duplicates were eliminated
        time_event, orbit_event = df.loc[CHANNEL_TRIGGER, ('TIME_ABS', 'ORBIT_CNT')]
        # check for events with ID less than previous one
        if evt_id <= last_evt_id:
          print('WARNING: Backward-jump in event number (current={0}, last={1})'.format(evt_id, last_evt_id))
          print('         Event skipped')
          if VERBOSE:
            print(allhits.loc[allhits["ORBIT_CNT"].isin(range(orbit_event-10,orbit_event+10))].loc[allhits["TDC_CHANNEL"].isin(channels)])
          continue
        
        # check for events with way larger ID than previous one
        if not args.events and last_evt_id > 0 and (evt_id - last_evt_id) > 20:
          print('WARNING: Large forward-jump in event number (current={0}, last={1})'.format(evt_id, last_evt_id))
          print('         Retaining current and removing previous event')
          # allhits.drop(allhits[allhits['EVENT_NR'] == last_evt_id].index, inplace=True)
          allhits.loc[allhits['EVENT_NR'] == last_evt_id, 'EVENT_NR'] = -1
          if VERBOSE:
            print(allhits.loc[allhits["ORBIT_CNT"].isin(range(orbit_event-10,orbit_event+10))].loc[allhits["TDC_CHANNEL"].isin(channels)])
          # don't 'continue' as this indicates only an issue when opening a new file (first event ID of a file being a result of a backward-jump)
        # Storing ID of the last event to detect jumps in EVENT_NR
        last_evt_id = evt_id

        # Looking for other hits within the time window of the event, taking into account latency
        # set ttrig based on run number (HARDCODED)
        time_offset = TIME_OFFSET
        # Defining t0 as time of the trigger channel corrected by latency offset
        tzero = time_event + time_offset
        ############################################
        # # FIXME: Correcting TIME0 for this particular event
        # tzero += 4.0
        ############################################
        event_window = (tzero + TIME_WINDOW[0], tzero + TIME_WINDOW[1])

        try:
            window = allhits['TIME_ABS'].between(event_window[0], event_window[1], inclusive=False)
            # print('event: {0:d}  duration: {1:.3f}'.format(evt_id, clock() - start))
        except Exception as e:
            print('WARNING: Exception when calculating window')

        # Calculating time of arrival of the different trigger signals
        df_trg = df['TIME_ABS'].reindex(CHANNELS_TRIGGER, fill_value=-111)
        times_trg = df_trg.values
        # Packing bits into 8bit integer and shifting by 5 positions to the right
        trg_bits = np.packbits(df_trg != -111) >> 5
        df_events.loc[grp, ['TIMEDIFF_TRG_20', 'TIMEDIFF_TRG_21', 'TRG_BITS', 'EVENT_NR', 'TIME0']] = (
            times_trg[2] - times_trg[0], times_trg[2] - times_trg[1], trg_bits, evt_id, tzero)
        # start = clock()
        # res = allhits[window | (allhits['evt_group'] == grp)]
        # print('event: {0:d}  duration: {1:.3f}'.format(evt_id, clock() - start))
        # continue

        # Storing hits of the event with corresponding event number and t0
        idx = allhits.index[window | (allhits['evt_group'] == grp)]
        hits = hits.append(pd.DataFrame(np.array([evt_id, tzero]*len(idx)).reshape([-1, 2]), index=idx, columns=['EVENT_NR', 'TIME0']))

    # Updating hits in the main dataframe with EVENT_NR and TIME0 values from detected events
    hits['EVENT_NR'] = hits['EVENT_NR'].astype(int)
    allhits.loc[hits.index, ['EVENT_NR', 'TIME0']] = hits[['EVENT_NR', 'TIME0']]

    # Removing the temporary grouping column
    allhits.drop('evt_group', axis=1, inplace=True)
    # Creating a column with time passed since last event
    df_events.set_index('EVENT_NR', inplace=True)
    # Removing events that have no hits
    if -1 in df_events.index:
        df_events.drop(-1, inplace=True)
    return df_events

def meantimer_results(df_hits, verbose=False):
    """Run meantimer over the group of hits"""
    sl = df_hits['SL'].iloc[0]
    # Getting a TIME column as a Series with TDC_CHANNEL_NORM as index
    df_time = df_hits.loc[:, ['TDC_CHANNEL_NORM', 'TIME_ABS', 'LAYER']]
    df_time.sort_values('TIME_ABS', inplace=True)
    # Split hits in groups where time difference is larger than maximum event duration
    grp = df_time['TIME_ABS'].diff().fillna(0)
    event_width_max = 1.1*TDRIFT
    grp[grp <= event_width_max] = 0
    grp[grp > 0] = 1
    grp = grp.cumsum().astype(np.uint16)
    df_time['grp'] = grp
    # Removing groups with less than 3 unique hits
    df_time = df_time[df_time.groupby('grp')['TDC_CHANNEL_NORM'].transform('nunique') >= 3]
    # Determining the TIME0 using triplets [no external trigger]
    tzeros = []
    angles = []
    # Processing each group of hits
    patterns = PATTERN_NAMES.keys()
    for grp, df_grp in df_time.groupby('grp'):
        df_grp.set_index('TDC_CHANNEL_NORM', inplace=True)
        # Selecting only triplets present among physically meaningful hit patterns
        channels = set(df_grp.index.astype(np.int16))
        triplets = set(itertools.permutations(channels, 3))
        triplets = triplets.intersection(patterns)
        # Grouping hits by the channel for quick triplet retrieval
        times = df_grp.groupby(df_grp.index)['TIME_ABS']
        # Analysing each triplet
        for triplet in triplets:
            triplet_times = [times.get_group(ch).values for ch in triplet]
            for t1 in triplet_times[0]:
                for t2 in triplet_times[1]:
                    for t3 in triplet_times[2]:
                        timetriplet = (t1, t2, t3)
                        if max(timetriplet) - min(timetriplet) > 1.1*TDRIFT:
                            continue
                        pattern = PATTERN_NAMES[triplet]
                        mean_time, angle = meantimereq(pattern, timetriplet)
                        if verbose:
                            print('{4:d} {0:s}: {1:.0f}  {2:+.2f}  {3}'.format(pattern, mean_time, angle, triplet, sl))
                        # print(triplet, pattern, mean_time, angle)
                        if not MEANTIMER_ANGLES[sl][0] < angle < MEANTIMER_ANGLES[sl][1]:
                            continue
                        tzeros.append(mean_time)
                        angles.append(angle)

    return tzeros, angles

def removezeros(arr):
    zeros = np.all(np.equal(arr, 0), axis=1)
    arr = arr[~zeros]
    return arr

def allowed_slope(xs,ys):
#checks if the slope is at most 60 degrees from the vertical between the start and end point
    x = sorted(xs)
    y = sorted(ys)
    if np.around(y[-1]-y[0]) == 0:
        slope = 100
    else:
        slope = float((x[-1]-x[0])/(y[-1]-y[0]))
    if slope > max_slope:
        return False
    else:
        return True


def find_fit(df):
# function to try possible combinations of points and select the one with the best line of fit
    chambs = df.groupby('y')
    list1 = []
    for i,chamb in chambs:
        list1.append(chamb.to_numpy())
    points = np.array(list(itertools.product(*list1)))

    #iterate over all possible combinations of points and return the fit with best chi squared
    chisq_best = 20. #maximum acceptable chi squared
    dof = 2 #degrees of freedom in the fit
    fit_best = []
    x_best = []
    y_best = []
    count = np.arange(len(points))
    for i in count:
        xs = [x[0] for x in points[i]]
        ys = [x[1] for x in points[i]]
        fit, chisq, _, _, _ = np.polyfit(ys,xs,1,full = True)
        x_fit = list(np.poly1d(fit)(ys))
        
        #ignore combinations with slopes that aren't allowed
        if allowed_slope(x_fit,ys) == True:
            #handles a combination with chisq << 1
            if chisq.size == 0:
                chisq_best = 0
                fit_best = fit
                x_best = xs
                y_best = ys 
            elif float(chisq)/dof < chisq_best:
                chisq_best = chisq/dof
                fit_best = fit
                x_best = xs
                y_best = ys
    
    fit_pts = list(np.poly1d(fit_best)(y_best))
    return x_best,y_best,fit_pts,float(chisq_best)

def local_reconstruction_xleft_xright(data,n):
#local reconstructions in parallel with processing
    df = pd.DataFrame()
    rej_count = 0
    accepted = 0
    xl0 = pd.DataFrame(data[data['SL'] == 0],columns = ('X_POS_LEFT','Z_POS'))
    xr0 = pd.DataFrame(data[data['SL'] == 0],columns = ('X_POS_RIGHT','Z_POS'))
    xl0 = xl0.rename({'X_POS_LEFT':'x','Z_POS':'y'},axis = 1)
    xr0 = xr0.rename({'X_POS_RIGHT':'x','Z_POS':'y'},axis = 1)
    pts0 = pd.concat([xl0,xr0])
    xl1 = pd.DataFrame(data[data['SL'] == 1],columns = ('X_POS_LEFT','Z_POS'))
    xr1 = pd.DataFrame(data[data['SL'] == 1],columns = ('X_POS_RIGHT','Z_POS'))
    xl1 = xl1.rename({'X_POS_LEFT':'x','Z_POS':'y'},axis = 1)
    xr1 = xr1.rename({'X_POS_RIGHT':'x','Z_POS':'y'},axis = 1)
    pts1 = pd.concat([xl1,xr1])
    xl2 = pd.DataFrame(data[data['SL'] == 2],columns = ('X_POS_LEFT','Z_POS'))
    xr2 = pd.DataFrame(data[data['SL'] == 2],columns = ('X_POS_RIGHT','Z_POS'))
    xl2 = xl2.rename({'X_POS_LEFT':'x','Z_POS':'y'},axis = 1)
    xr2 = xr2.rename({'X_POS_RIGHT':'x','Z_POS':'y'},axis = 1)
    pts2 = pd.concat([xl2,xr2])
    xl3 = pd.DataFrame(data[data['SL'] == 3],columns = ('X_POS_LEFT','Z_POS'))
    xr3 = pd.DataFrame(data[data['SL'] == 3],columns = ('X_POS_RIGHT','Z_POS'))
    xl3 = xl3.rename({'X_POS_LEFT':'x','Z_POS':'y'},axis = 1)
    xr3 = xr3.rename({'X_POS_RIGHT':'x','Z_POS':'y'},axis = 1)
    pts3 = pd.concat([xl3,xr3])
              
    #filter out events where a chamber didn't have enough hits for a reconstruction
    if len(pts0) == 0 or len(pts1) == 0 or len(pts2) == 0 or len(pts3) == 0:
        #print('Invalid event: One or more chambers had no hits')
        rej_count += 1
    else:
        #return a local reconstruction (reconstruction within 1 chamber) for each event
        x0,z0,fit0,chi0 = find_fit(pts0)
        x1,z1,fit1,chi1 = find_fit(pts1)
        x2,z2,fit2,chi2 = find_fit(pts2)
        x3,z3,fit3,chi3 = find_fit(pts3)
                
        #filter out events with fits below the chi squared threshold
        if len(x0) == 0 or len(x1) == 0 or len(x2) == 0 or len(x3) == 0:
            #print('This event had no good fits')
            rej_count += 1
                
        #put the relevant information into a dataframe
        else:
            accepted += 1
            fig1,axes = plt.subplots(nrows = 2,ncols = 2,figsize =(8,8),constrained_layout=True)
            axes[0,0].plot(fit0,z0)
            axes[0,0].scatter(x0,z0,color = 'black',marker = '.')
            axes[0,0].set_title('Event '+str(n)+' Chamber 1')
            axes[0,0].set_xlim(min(x0)-5,max(x0)+5)
            axes[0,0].set_ylim(0, 52)
            axes[0,1].plot(fit1,z1)
            axes[0,1].scatter(x1,z1,color = 'black',marker = '.')
            axes[0,1].set_title('Event '+str(n)+' Chamber 2')
            axes[0,1].set_xlim(min(x1)-5,max(x1)+5)
            axes[0,1].set_ylim(0, 52)
            axes[1,0].plot(fit2,z2)
            axes[1,0].scatter(x2,z2,color = 'black',marker = '.')
            axes[1,0].set_title('Event '+str(n)+' Chamber 3')
            axes[1,0].set_xlim(min(x2)-5,max(x2)+5)
            axes[1,0].set_ylim(0, 52)
            axes[1,1].plot(fit3,z3)
            axes[1,1].scatter(x3,z3,color = 'black',marker = '.')
            axes[1,1].set_title('Event '+str(n)+' Chamber 4')
            axes[1,1].set_xlim(min(x3)-5,max(x3)+5)
            axes[1,1].set_ylim(0, 52)
            label = 'Local Reconstructions: Event '+str(n)
            fig1.savefig('plots/'+label+'.png')
            plt.close(fig1)
            ch1 = x0+z0
            ch2 = x1+list(np.asarray(z1)+4*ZCELL)
            ch3 = x2+list(np.asarray(z2)+Z_SEP)
            ch4 = x3+list(np.asarray(z3)+4*ZCELL+Z_SEP)
            chambs = [ch1,ch2,ch3,ch4]
                    
            for i in np.arange(len(chambs)):
                df2 = pd.DataFrame(chambs[i],dtype = float)
                df = df.append(df2.T,ignore_index = True)

    return df,accepted

def total_reconstruction(df,n,fig):
#reconstructing paths in parallel with Nazar's processing
    count = len(df.index)
    accepted = 0
    j = 0
    while j < count:
        #iterate through the dataframe, plotting one line per event
        ch1 = list(df.loc[j,:].dropna())
        ch2 = list(df.loc[j+1,:].dropna())
        ch3 = list(df.loc[j+2,:].dropna())
        ch4 = list(df.loc[j+3,:].dropna())

        x1 = ch1[:len(ch1)//2]
        z1 = ch1[len(ch1)//2:]
        y2 = ch2[:len(ch2)//2]
        z2 = ch2[len(ch2)//2:]
        xfit1 = np.polyfit(z1,x1,1)
        yfit1 = np.polyfit(z2,y2,1)
        y1 = list(np.poly1d(yfit1)(z1))
        x2 = list(np.poly1d(xfit1)(z2))

        x3 = ch3[:len(ch3)//2]
        z3 = ch3[len(ch3)//2:]
        y4 = ch4[:len(ch4)//2]
        z4 = ch4[len(ch4)//2:]
        xfit2 = np.polyfit(z3,x3,1)
        yfit2 = np.polyfit(z4,y4,1)
        y3 = list(np.poly1d(yfit2)(z3))
        x4 = list(np.poly1d(xfit2)(z4))

        #discard if there is not good agreement between corresponding chambers
        x1new = x1+x3
        z1new = z1+z3
        y1new,chisq1,_,_,_ = np.polyfit(x1new,z1new,1,full = True)
        y2new = y2+y4
        z2new = z2+z4
        x2new,chisq2,_,_,_ = np.polyfit(y2new,z2new,1,full = True)

        if float(chisq1/2) < chisq_2d and float(chisq2/2) < chisq_2d:
            x1.extend(x2)
            x1.extend(x3)
            x1.extend(x4)
            y1.extend(y2)
            y1.extend(y3)
            y1.extend(y4)
            z1.extend(z2)
            z1.extend(z3)
            z1.extend(z4)

            #find a plane of best fit for the x-z axis and y-z axis
            A_xz = np.vstack((x1, np.ones(len(x1)))).T
            m_xz,chix,_,_ = np.linalg.lstsq(A_xz, z1,rcond=None)
            A_yz = np.vstack((y1, np.ones(len(y1)))).T
            m_yz,chiy,_,_ = np.linalg.lstsq(A_yz, z1,rcond=None)

            if chix/3 < chisq_3d and chiy/3 < chisq_3d:
                #calculate points along the intersection of the planes to get best fit line for data overall
                z_final = np.linspace(0,888)
                x_final = (z_final - m_xz[1])/m_xz[0]
                y_final = (z_final - m_yz[1])/m_yz[0]
                label = 'Event '+str(n)
                #fig = plt.figure(figsize =(6,6))
                ax = fig.add_subplot(111, projection='3d')
                ax.scatter(x1,y1,z1)
                ax.plot(x_final,y_final,z_final,label = label)
                ax.set_xlabel("X")
                ax.set_ylabel("Y")
                ax.set_zlabel("Z")
                ax.set_title(label)
                # set limits of the axes so that they match the dimensions of the chambers
                ax.set_xlim(0, 693)
                ax.set_ylim(0, 693)
                ax.set_proj_type('ortho')
                fig.savefig('plots/'+label+'.png')
                accepted += 1
                plt.clf()
                plt.close(fig)
               
        j += 4
    return accepted

def reconstruct(df,n,fig):
 #version of reconstruction that runs simultaneously with processing
    data,local = local_reconstruction_xleft_xright(df,n)
    if len(data.index) != 0:
        count = total_reconstruction(data,n,fig)
        return local,count
    else:
        return local,0

def local_reconstruction_all(path):
    df= pd.DataFrame(columns = np.arange(20))
    rej_count = 0
    events = 0
    with open(path) as fp:
        for i, line in enumerate(fp):
        #convert each line of text file (ie. event) to a readable list of the relevant data
            events +=1
            data = line.split(' ')
            data = data[2:]
            n = len(data)
            index = 0
            j0 = j1 = j2 = j3 = 0
            pts0 = np.zeros((2*n,2))
            pts1 = np.zeros((2*n,2))
            pts2 = np.zeros((2*n,2))
            pts3 = np.zeros((2*n,2))
            while index < n:
                if float(data[index]) == 0:
                    pts0[j0,0] = float(data[index+2])
                    pts0[j0+1,0] = float(data[index+3])
                    pts0[j0,1] = pts0[j0+1,1] = float(data[index+4])
                    index +=5
                    j0 += 2
                elif float(data[index]) == 1.:
                    pts1[j1,0] = float(data[index+2])
                    pts1[j1+1,0] = float(data[index+3])
                    pts1[j1,1] = pts1[j1+1,1] = float(data[index+4])
                    index +=5
                    j1 += 2
                elif float(data[index]) == 2.:
                    pts2[j2,0] = float(data[index+2])
                    pts2[j2+1,0] = float(data[index+3])
                    pts2[j2,1] = pts2[j2+1,1] = float(data[index+4])
                    index +=5
                    j2 += 2
                else:
                    pts3[j3,0] = float(data[index+2])
                    pts3[j3+1,0] = float(data[index+3])
                    pts3[j3,1] = pts3[j3+1,1] = float(data[index+4])
                    index +=5
                    j3 += 2
                        
            pts0 = pd.DataFrame(removezeros(pts0),columns = ('x','y'))
            pts1 = pd.DataFrame(removezeros(pts1),columns = ('x','y'))
            pts2 = pd.DataFrame(removezeros(pts2),columns = ('x','y'))
            pts3 = pd.DataFrame(removezeros(pts3),columns = ('x','y'))
                
            #filter out events where a chamber didn't have enough hits for a reconstruction
            if len(pts0) == 0 or len(pts1) == 0 or len(pts2) == 0 or len(pts3) == 0:
                #print('Invalid event: One or more chambers had no hits')
                rej_count += 1
                continue
            
            #return a local reconstruction (reconstruction within 1 chamber) for each event
            x0,z0,fit0,chi0 = find_fit(pts0)
            x1,z1,fit1,chi1 = find_fit(pts1)
            x2,z2,fit2,chi2 = find_fit(pts2)
            x3,z3,fit3,chi3 = find_fit(pts3)
                
            #filter out events with fits below the chi squared threshold
            if len(x0) == 0 or len(x1) == 0 or len(x2) == 0 or len(x3) == 0:
                rej_count += 1
                
            #put the relevant information into a dataframe
            else:
                ch1 = x0+z0
                ch2 = x1+list(np.asarray(z1)+4*ZCELL)
                ch3 = x2+list(np.asarray(z2)+Z_SEP)
                ch4 = x3+list(np.asarray(z3)+4*ZCELL+Z_SEP)
                ch1.insert(0,events)
                ch2.insert(0,events)
                ch3.insert(0,events)
                ch4.insert(0,events)
                chambs = [ch1,ch2,ch3,ch4]
                    
                for i in np.arange(len(chambs)):
                    df2 = pd.DataFrame(chambs[i],dtype = float)
                    df = df.append(df2.T,ignore_index = True)
                    
    accepted = events-rej_count
    fp.close()
    return df

def total_reconstruction_all(df,start,end):
    plt.close('all')
    fig = plt.figure(figsize =(6,6))
    ax = Axes3D(fig)
    ax.set_xlabel("X")
    ax.set_ylabel("Y")
    ax.set_zlabel("Z")
    count = len(df.index)
    j = 0
    accepted = 0
    start = int(start)
    end = int(end)
    while j < count:
        if start*4 <= j < end*4:
            #iterate through the dataframe, plotting one line per event
            ch1 = list(df.loc[j,:].dropna())
            ch2 = list(df.loc[j+1,:].dropna())
            ch3 = list(df.loc[j+2,:].dropna())
            ch4 = list(df.loc[j+3,:].dropna())
            x1 = ch1[1:len(ch1)//2+1]
            z1 = ch1[len(ch1)//2+1:]
            y2 = ch2[1:len(ch2)//2+1]
            z2 = ch2[len(ch2)//2+1:]
            xfit1 = np.polyfit(z1,x1,1)
            yfit1 = np.polyfit(z2,y2,1)
            y1 = list(np.poly1d(yfit1)(z1))
            x2 = list(np.poly1d(xfit1)(z2))

            x3 = ch3[1:len(ch3)//2+1]
            z3 = ch3[len(ch3)//2+1:]
            y4 = ch4[1:len(ch4)//2+1]
            z4 = ch4[len(ch4)//2+1:]
            xfit2 = np.polyfit(z3,x3,1)
            yfit2 = np.polyfit(z4,y4,1)
            y3 = list(np.poly1d(yfit2)(z3))
            x4 = list(np.poly1d(xfit2)(z4))
            event_nr = int(ch1[0])

            #discard if there is not good agreement between corresponding chambers
            x1new = x1+x3
            z1new = z1+z3
            y1new,chisq1,_,_,_ = np.polyfit(x1new,z1new,1,full = True)
            y2new = y2+y4
            z2new = z2+z4
            x2new,chisq2,_,_,_ = np.polyfit(y2new,z2new,1,full = True)

            #if limits are provided,only plot the specified range of events
            if float(chisq1/2) < chisq_2d and float(chisq2/2) < chisq_2d:
                x1.extend(x2)
                x1.extend(x3)
                x1.extend(x4)
                y1.extend(y2)
                y1.extend(y3)
                y1.extend(y4)
                z1.extend(z2)
                z1.extend(z3)
                z1.extend(z4)

                #find a plane of best fit for the x-z axis and y-z axis
                A_xz = np.vstack((x1, np.ones(len(x1)))).T
                m_xz,chix,_,_ = np.linalg.lstsq(A_xz, z1,rcond=None)
                A_yz = np.vstack((y1, np.ones(len(y1)))).T
                m_yz,chiy,_,_ = np.linalg.lstsq(A_yz, z1,rcond=None)

                #calculate points along the intersection of the planes to get best fit line for data overall
                if chix/3 < chisq_3d and chiy/3 < chisq_3d:
                    accepted += 1
                    z_final = np.linspace(0,888)
                    x_final = (z_final - m_xz[1])/m_xz[0]
                    y_final = (z_final - m_yz[1])/m_yz[0]
                    label = 'Event '+str(event_nr)
                    ax.scatter(x1,y1,z1)
                    ax.plot(x_final,y_final,z_final,label = label)
                    ax.set_xlim(0, 693)
                    ax.set_ylim(0, 693)
                    ax.legend(loc = 'upper left')

        j+=4
    #print('Events With Acceptable Global Reconstruction: '+str(accepted)+' out of '+str(count//4))
    plt.show()

def reconstruct_all(filein,start = 0,end = None):
    #version of reconstruct that runs after processing to plot multiple events together if desired
    data = local_reconstruction_all(filein)
    total_reconstruction_all(data,start,end)

def save_root(dfs, df_events, output_path,start,end):
    """Prints output to a text file with one event per line, sequence of hits in a line"""
    if not dfs:
        print('WARNING: No hits for writing into a text file')
        return
    # Concatenating dataframe from different SLs
    df_all = pd.concat(dfs)
    # Selecting only physical or trigger hits [for writing empty events as well]
    df_all = df_all[(df_all['TIME0'] > 0) | ((df_all['FPGA'] == CHANNEL_TRIGGER[0]) & (df_all['TDC_CHANNEL'] == CHANNEL_TRIGGER[1]))]
    events = df_all.groupby('EVENT_NR')
    local_count = 0
    global_count = 0
    if end == None:
        start = int(start)
        end = len(events)
    else:
        start = int(start)
        end = int(end)
    layers = range(4)
    print('### Writing {0:d} events to file: {1:s}'.format(end, output_path))
    print('### Reconstructing events...')
    with open(output_path, 'w') as outfile:
        fig = plt.figure(figsize =(6,6))
        i = 0
        for event, df in events:
            if start <= i < end:
                local,globe = reconstruct(df,event,fig)
                ch_sel = (df['TDC_CHANNEL'] != CHANNEL_TRIGGER[1])
                n_layer_hits = df.loc[ch_sel].sort_values('SL').groupby('SL').size().reindex(layers).fillna(0).astype(int).tolist()
                nhits = df.loc[ch_sel].shape[0]
                orbit, tzero = df.iloc[0][['ORBIT_CNT', 'TIME0']]
                # Merging all hits
                line = '{0:d} {1:d}'.format(event, nhits)
                if nhits > 0:
                    line += ' ' + ' '.join(['{0:.0f} {1:.0f} {2:.8f} {3:.8f} {4:.1f}'.format(*values)
                                           for values in df.loc[ch_sel, ['SL','LAYER', 'X_POS_LEFT', 'X_POS_RIGHT','Z_POS']].values])
                outfile.write(line+'\n')
                i += 1
                local_count += local
                global_count += globe

    print('### Locally Reconstructed '+str(local_count)+' out of '+str(i)+' events in the range given')
    print('### Globally Reconstructed '+str(global_count)+' out of '+str(local_count)+' events in the range given')

############################################# READING DATA FROM CSV INPUT
def read_data(input_files):
    """
    Reading data from CSV file into a Pandas dataframe, applying selection and sorting
    """
    # Reading each file and merging into 1 dataframe
    hits = []
    for index, file in enumerate(input_files):
        skipLines = 0
        if 'data_000000' in file:
            skipLines = range(1,131072)
        df = pd.read_csv(file, nrows=args.number, skiprows=skipLines, engine='c')
        # Removing possible incomplete rows e.g. last line of last file
        df.dropna(inplace=True)
        # Converting to memory-optimised data types
        for name in ['HEAD', 'FPGA', 'TDC_CHANNEL', 'TDC_MEAS']:
            df[name] = df[name].astype(np.uint8)
        for name in ['BX_COUNTER']:
            df[name] = df[name].astype(np.uint16)
        for name in ['ORBIT_CNT']:
            df[name] = df[name].astype(np.uint32)
        hits.append(df)
    allhits = pd.concat(hits, ignore_index=True, copy=False)
    df_events = None
    print('### Read {0:d} hits from {1:d} input files'.format(allhits.shape[0], len(hits)))
    # retain all words with HEAD=1
    allhits.drop(allhits.index[allhits['HEAD'] != 1], inplace=True)
    # Removing hits with TDC_CHANNEL 139
    allhits.drop(allhits.index[allhits['TDC_CHANNEL'] == 139], inplace=True)
    # Removing unused columns to save memory foot-print
    allhits.drop('HEAD', axis=1, inplace=True)
    ### # Increase output of all channels with id below 130 by 1 ns --> NOT NEEDED
    ### allhits.loc[allhits['TDC_CHANNEL'] <= 130, 'TDC_MEAS'] = allhits['TDC_MEAS']+1 
    # Calculate absolute time in ns of each hit
    allhits['TIME_ABS'] = (allhits['ORBIT_CNT'].astype(np.float64)*DURATION['orbit'] + 
                           allhits['BX_COUNTER'].astype(np.float64)*DURATION['bx'] + 
                           allhits['TDC_MEAS'].astype(np.float64)*DURATION['tdc']).astype(np.float64)
    # Adding columns to be calculated
    nHits = allhits.shape[0]
    allhits['TIME0'] = np.zeros(nHits, dtype=np.float64)
    allhits['EVENT_NR'] = np.ones(nHits, dtype=np.uint32) * -1
    # Calculating additional info about the hits
    conditions  = [
        (allhits['TDC_CHANNEL'] % 4 == 1 ),
        (allhits['TDC_CHANNEL'] % 4 == 2 ),
        (allhits['TDC_CHANNEL'] % 4 == 3 ),
        (allhits['TDC_CHANNEL'] % 4 == 0 ),
    ]
    chanshift_x = [  0,            -1,           0,            -1,        ]
    layer_z     = [  1,            3,            2,            4,         ]
    pos_z       = [  ZCELL*3.5,    ZCELL*1.5,    ZCELL*2.5,    ZCELL*0.5, ]
    posshift_x  = [  0,            0,            0.5,          0.5,       ]
    # Adding columns
    allhits['LAYER']      = np.select(conditions, layer_z,      default=0).astype(np.uint8)
    allhits['X_CHSHIFT']  = np.select(conditions, chanshift_x,  default=0).astype(np.int8)
    allhits['X_POSSHIFT'] = np.select(conditions, posshift_x,   default=0).astype(np.float16)
    allhits['Z_POS']      = np.select(conditions, pos_z,        default=0).astype(np.float16)

    # conditions  = FPGA number and TDC_CHANNEL in range
    # SL         <- superlayer = chamber number from 0 to 3 (0,1 FPGA#0 --- 2,3 FPGA#1)
    conditions_SL = [
        ((allhits['FPGA'] == 0) & (allhits['TDC_CHANNEL'] <= NCHANNELS )),
        ((allhits['FPGA'] == 0) & (allhits['TDC_CHANNEL'] > NCHANNELS ) & (allhits['TDC_CHANNEL'] <= 2*NCHANNELS )),
        ((allhits['FPGA'] == 1) & (allhits['TDC_CHANNEL'] <= NCHANNELS )),
        ((allhits['FPGA'] == 1) & (allhits['TDC_CHANNEL'] > NCHANNELS ) & (allhits['TDC_CHANNEL'] <= 2*NCHANNELS )),
    ]
    allhits['SL'] = np.select(conditions_SL, [0, 1, 2, 3], default=-1).astype(np.int8)
    # Correcting absolute time by per-chamber latency
    for sl in range(4):
        sel = allhits['SL'] == sl
        allhits.loc[sel, 'TIME_ABS'] = allhits.loc[sel, 'TIME_ABS'] + TIME_OFFSET_SL[sl]

    # define channel within SL
    allhits['TDC_CHANNEL_NORM'] = (allhits['TDC_CHANNEL'] - NCHANNELS * (allhits['SL']%2)).astype(np.uint8)

    # Detecting events based on EVENT_NR signals
    if args.event:
        df_events = calc_event_numbers(allhits)
    # Assigning orbit counter as event number
    else:
        # Grouping hits separated by large time gaps together
        allhits.sort_values('TIME_ABS', inplace=True)
        grp = allhits['TIME_ABS'].diff().fillna(0)
        grp[grp <= 1.1*TDRIFT] = 0
        grp[grp > 0] = 1
        grp = grp.cumsum().astype(np.int32)
        allhits['EVENT_NR'] = grp
        events = allhits.groupby('EVENT_NR')
        nHits = events.size()
        nHits_unique = events['TDC_CHANNEL'].nunique()
        nSL = events['SL'].nunique()
        # Selecting only events with manageable numbers of hits
        events = nHits.index[(nSL >= args.chambers) & (nHits_unique >= (MEANTIMER_CLUSTER_SIZE * 3)) & (nHits <= args.max_hits)]
        # Marking events that don't pass the basic selection
        sel = allhits['EVENT_NR'].isin(events)
        allhits.loc[~sel, 'EVENT_NR'] = -1
        df_events = pd.DataFrame(data={'EVENT_NR': events})
        df_events['TIME0'] = -1
        df_events['TRG_BITS'] = -1
        df_events['TIMEDIFF_TRG_20'] = -1e9
        df_events['TIMEDIFF_TRG_21'] = -1e9
        df_events.set_index('EVENT_NR', inplace=True)
    # Removing hits with no event number
    allhits.drop(allhits.index[allhits['EVENT_NR'] == -1], inplace=True)
    # Calculating event times
    df_events['TIME0_BEFORE'] = df_events['TIME0'].diff().fillna(0)
    df_events['TIME0_AFTER'] = df_events['TIME0'].diff(-1).fillna(0)
    
    # Removing hits with irrelevant tdc channels
    allhits.drop(allhits.index[(allhits['TDC_CHANNEL_NORM'] > NCHANNELS)
                 & ~((allhits['FPGA'] == CHANNEL_TRIGGER[0]) 
                     & (allhits['TDC_CHANNEL'] == CHANNEL_TRIGGER[1])
                 )], inplace=True)
    # Removing events that don't pass acceptance cuts
    if args.accepted:
        select_accepted_events(allhits, df_events)
    nHits = allhits.shape[0]
    # Adding extra columns to be filled in the analyse method
    allhits['TIMENS'] = np.zeros(nHits, dtype=np.float16)
    allhits['X_POS_LEFT'] = np.zeros(nHits, dtype=np.float32)
    allhits['X_POS_RIGHT'] = np.zeros(nHits, dtype=np.float32)


    #############################################
    ### DATA HANDLING 

    if VERBOSE:
        print('')
        print('dataframe size                   :', len(allhits))
        print('')

    if VERBOSE:
        print('dataframe size (no trigger hits) :', len(allhits))
        print('')
        print('min values in dataframe')
        print(allhits[['TDC_CHANNEL','TDC_CHANNEL_NORM','TDC_MEAS','BX_COUNTER','ORBIT_CNT']].min())
        print('')
        print('max values in dataframe')
        print(allhits[['TDC_CHANNEL','TDC_CHANNEL_NORM','TDC_MEAS','BX_COUNTER','ORBIT_CNT']].max())
        print('')

    return allhits, df_events


def event_accepted(df, cut_max_hits=False):
    """Checks whether the event passes acceptance cuts"""
    # Calculating numbers of hit layers in each chamber
    nLayers = df.groupby('SL')['LAYER'].agg('nunique')
    # Skipping events that have no minimum number of chambers with 3+ layers of hits
    if nLayers[nLayers >= 3].shape[0] < MEANTIMER_SL_MULT_MIN:
        return False
    # Calculating numbers of hits in each chamber
    grp = df.groupby('SL')['TDC_CHANNEL_NORM']
    nHits = grp.agg('nunique')
    # Skipping if has at least one chamber with too few hits
    if nHits[nHits >= NHITS_SL[0]].shape[0] < args.chambers:
        return False
    nHits = grp.agg('size')
    # Skipping if has at least one chamber with too many hits
    if cut_max_hits and nHits[nHits > NHITS_SL[1]].shape[0] > 0:
        return False
    # return True
    # Skipping events that don't have the minimum number of similar meantimer solutions
    tzeros_all = {}
    # Starting from SLs with smallest N of hits
    sl_ids = nHits.loc[nLayers >= 3].sort_values().index
    nSLs = len(sl_ids)
    nSLs_meant = 0
    event = df.iloc[0]['EVENT_NR']
    for iSL, SL in enumerate(sl_ids):
        # Stopping if required number of SLs can't be regardless of the following SLs
        # if nSLs - iSL + nSLs_meant < MEANTIMER_SL_MULT_MIN:
        #     break
        tzeros = meantimer_results(df[df['SL'] == SL])[0]
        if len(tzeros) > 0:
            nSLs_meant += 1
        tzeros_all[SL] = tzeros
    tzero, tzeros, nSLs = mean_tzero(tzeros_all)
    if len(tzeros) < MEANTIMER_CLUSTER_SIZE:
        return False
    return tzero, tzeros, tzeros_all


def select_accepted_events(allhits, events): 
    """Removes events that don't pass acceptance cuts"""
    print('### Removing events outside acceptance')
    hits = allhits[allhits['TDC_CHANNEL_NORM'] <= NCHANNELS]
    sel = pd.concat([(hits['SL'] == sl) & (hits['TDC_CHANNEL_NORM'].isin(ch)) 
                    for sl, ch in ACCEPTANCE_CHANNELS.items()], axis=1).any(axis=1)
    groups = hits[sel].groupby('EVENT_NR')
    events_accepted = []
    n_events = len(groups)
    n_events_processed = 0
    print('### Checking {0:d} events'.format(n_events))
    events['CELL_HITS_MULT_MAX'] = 1
    events['CELL_HITS_DT_MIN'] = -1
    events['CELL_HITS_DT_MAX'] = -1
    sl_channels = None

    for event, df in groups:
        n_events_processed += 1
        print_progress(n_events_processed, n_events)
        # Accepting only specified events if provided
        if args.events and event not in args.events:
            continue
        # Selecting only events that have 1+ hits in a single cell
        if args.double_hits:
            cellHits = df.groupby(['SL', 'TDC_CHANNEL_NORM'])['TIME_ABS']
            nHits_max = cellHits.agg('size').max()
            if nHits_max < 2:
                continue
            dt_min = 999
            dt_max = -1
            for cell, hits in cellHits:
                if len(hits) < 2:
                    continue
                hits_sorted = np.sort(hits.values)
                dt_min = min(dt_min, hits_sorted[1] - hits_sorted[0])
                dt_max = max(dt_max, hits_sorted[-1] - hits_sorted[0])
            events.loc[event, ['CELL_HITS_MULT_MAX', 'CELL_HITS_DT_MIN', 'CELL_HITS_DT_MAX']] = [nHits_max, dt_min, dt_max]
            # Accepting the event
            events_accepted.append(event)
        # Skipping events that don't have hits exactly in the defined channels
        channels_ok = True
        if sl_channels:
            for sl, chs in sl_channels.items():
                if sorted(df[df['SL']==sl]['TDC_CHANNEL_NORM'].tolist()) == chs:
                    continue
                channels_ok = False
                break
            if not channels_ok:
                continue
        tzero_result = event_accepted(df, cut_max_hits=args.event)
        if not tzero_result:
            continue
        # Checking event for acceptance with different t0 candidates
        tzero, tzeros, tzeros_all = tzero_result
        df_clusters = tzero_clusters(tzeros_all)
        nClusters = df_clusters['cluster'].nunique()
        # Skipping event if no t0 cluster found
        if nClusters < 1:
            continue
        tzero = -1.0
        for cluster_id, df_cluster in df_clusters.groupby('cluster'):
            if len(df_cluster) < MEANTIMER_CLUSTER_SIZE:
                continue
            cluster = df_cluster['t0'].values
            tzero_cand = cluster.mean()
            # Trying acceptance cuts with a subset of hits from this orbit within the event time window
            window = ((df['TIME_ABS'] >= (tzero_cand + TIME_WINDOW[0])) & (df['TIME_ABS'] <= (tzero_cand + TIME_WINDOW[1]))).index
            tzero_result_cand = event_accepted(df.loc[window], cut_max_hits=True)
            if not tzero_result_cand:
                continue
            tzero = tzero_cand
            break
        if tzero < 0:
            continue
        # Accepting the event
        events_accepted.append(event)
        # Updating the TIME0 with meantimer result
        if args.update_tzero or not args.event:
            events.loc[event, 'TIME0'] = tzero
            if args.event:
                # Updating t0 of all hits directly if using external trigger
                allhits.loc[allhits['EVENT_NR'] == event, 'TIME0'] = tzero
            else:
                # Removing the old event number and applying only to hits in the window
                allhits.loc[allhits['EVENT_NR'] == event, 'EVENT_NR'] = -1
                # Updating t0 of hits in the event time window
                start = tzero + TIME_WINDOW[0]
                end = tzero + TIME_WINDOW[1]
                window = (allhits['TIME_ABS'] >= start) & (allhits['TIME_ABS'] <= end)
                allhits.loc[window, ['TIME0', 'EVENT_NR']] = [tzero, event]
    events.drop(events.index[~events.index.isin(events_accepted)], inplace=True)
    allhits.drop(allhits.index[~allhits['EVENT_NR'].isin(events_accepted)], inplace=True)
    print('### Selected {0:d}/{1:d} events in acceptance'.format(len(events_accepted), n_events))


def sync_triplets(results, df_events):
    """Synchronise events from triplet results in different SLs that were processed in parallel"""
    df_events['MEANTIMER_SL_MULT'] = -1
    df_events['MEANTIMER_MIN'] = -1
    df_events['MEANTIMER_MAX'] = -1
    df_events['MEANTIMER_MEAN'] = -1
    df_events['MEANTIMER_MULT'] = -1
    df_events['HITS_MULT'] = -1
    df_events['HITS_MULT_ACCEPTED'] = -1
    if not results:
        return
    groups = pd.concat([result[2] for result in results]).groupby(EVT_COL)
    print('### Performing triplets analysis on {0:d} events'.format(len(groups)))
    # Splitting event numbers into groups with different deviations from the trigger
    deviations = [0,2,4,6,8,10]
    event_deviations = {}
    for dev in deviations:
        event_deviations[dev] = []
    # Analysing each event
    n_events = len(groups)
    n_events_processed = 0
    for event, df in groups:
        n_events_processed += 1
        print_progress(n_events_processed, n_events)
        nHits = df.shape[0]
        # Selecting only hits in the acceptance region
        sel = pd.concat([(df['SL'] == sl) & (df['TDC_CHANNEL_NORM'].isin(ch)) 
                    for sl, ch in ACCEPTANCE_CHANNELS.items()], axis=1).any(axis=1)
        df = df[sel]
        nHitsAcc = df.shape[0]
        df_events.loc[event, ['HITS_MULT_ACCEPTED', 'HITS_MULT']] = (nHitsAcc, nHits)
        # Checking TIME0 found in each chamber
        tzeros = {}
        time0 = df_events.loc[event, 'TIME0']
        for sl, df_sl in df.groupby('SL'):
            # print('--- SL: {0:d}'.format(sl))
            nLayers = len(df_sl.groupby('LAYER'))
            # Skipping chambers that don't have 3 layers of hits
            if nLayers < 3:
                continue
            tzeros_sl, angles_sl = meantimer_results(df_sl, verbose=False)
            if sl not in tzeros:
                tzeros[sl] = []
            tzeros[sl].extend(tzeros_sl)
            meantimers_info = results[sl][3]
            for name in ['t0_dev', 't0_angle', 'hit_angles_diff', 'hit_means_diff']:
                if name not in meantimers_info:
                    meantimers_info[name] = []
            meantimers_info['t0_dev'].extend([time0 - tzero for tzero in tzeros_sl])
            meantimers_info['t0_angle'].extend(angles_sl)
        # Calculating the mean of the t0 candidates excluding outliers
        tzero, tzeros, nSLs = mean_tzero(tzeros)
        if len(tzeros) < 1:
            df_events.loc[event, 'MEANTIMER_MULT'] = 0
        else:
            df_events.loc[event, ['MEANTIMER_MEAN', 'MEANTIMER_MIN', 'MEANTIMER_MAX', 'MEANTIMER_MULT', 'MEANTIMER_SL_MULT']
            ] = (tzero, np.min(tzeros), np.max(tzeros), len(tzeros), nSLs)
        deviation = abs(tzero - time0)
        for dev in reversed(deviations):
            if deviation > float(dev):
                event_deviations[dev].append(event)
                break

def process(input_files,start,end):
    """Do the processing of input files and produce all outputs split into groups if needed"""
    jobs = []  
    results = []

    parts = os.path.split(input_files[0])
    run = os.path.split(parts[0])[-1]

    if args.layer is None:
        # Processing all layers in parallel threads
        allhits, df_events = read_data(input_files)
        # br()
        for sl in range(4):
        # Avoiding parallel processing due to memory duplication by child processes
            results.append(analyse(allhits[allhits['SL'] == sl].copy(), sl))
        # pool = Pool(4)
        # results = pool.map(analyse_parallel, jobs)
    else:
        # Running the analysis on SL 0
        allhits, df_events = read_data(input_files)
        results.append(analyse(allhits[allhits['SL'] == args.layer], args.layer))
    # Matching triplets from same event
    if args.triplets:
        sync_triplets(results, df_events)
    
    print('### Filling output')
    for result in results:
        if not result:
            continue

        # Writing data to CSV
        SL = result[0]
        if args.csv:
            df_out = df[['SL','LAYER','WIRE_NUM','TDC_CHANNEL_NORM','TIMENS','TIME0','X_POS_LEFT','X_POS_RIGHT','Z_POS']]
            df_out.to_csv('out_df_{0:d}.csv'.format(SL))

    # Determining output file path
    file = os.path.splitext(parts[-1])[0]
    if args.events:
        file += '_e'+'_'.join(['{0:d}'.format(ev) for ev in args.events])
    if args.update_tzero:
        file += '_t0'
    if args.suffix:
        file += '_{0:s}'.format(args.suffix)

    ### GENERATE TEXT OUTPUT [one event per line]
    if args.root:
        dfs = []
        for result in results:
            if not len(result) > 2:
                continue
            # Collecting dataframes with all hits
            dfs.append(result[1])
        out_path = os.path.join('text', run, file+'.txt')
        try:
            os.makedirs(os.path.dirname(out_path))
        except:
            pass
        save_root(dfs, df_events, out_path,start,end)

    return out_path


for i in range(0, len(args.inputs), args.group):
    files = args.inputs[i:i+args.group]
    print('############### Starting processing files {0:d}-{1:d} out of total {2:d}'.format(i, i+len(files)-1, len(args.inputs)))
    # Processing the input files
    fp = process(files,start = args.range[0],end = args.range[1])
    plt.close('all')
    if args.join[1] != None:
    	reconstruct_all(fp,start = args.join[0],end = args.join[1])
    print('### Done')
    
