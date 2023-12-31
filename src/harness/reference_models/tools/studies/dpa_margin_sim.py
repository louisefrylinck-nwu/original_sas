#    Copyright 2018 SAS Project Authors. All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License");
#    you may not use this file except in compliance with the License.
#    You may obtain a copy of the License at
#
#        http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS,
#    WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#    See the License for the specific language governing permissions and
#    limitations under the License.

"""DPA move list and TH interference check simulator based on IPR configs.

This is a simulation of the DPA test harness process for purpose of analyzing
the pass/fail criteria of the test harness.
It has 2 modes of operations:

 - standalone simulator: analysis of a IPR/MCP or reg/grant configuration.
 - test harness log analyzer: analysis of DPA CSV logs produced during IPR/MCP runs.

Disclaimer:
====================
This simulator/analyzer is a tool provided for helping in the analyzis of the DPA
interference checks between reference model and SAS UUT.
Those interference checks have an inherently randomness to them, and this tool cannot
provide definite conclusion: it only provides some hints on why a test can fail
for randomness reasons although the SAS UUT perfectly implement a procedure fully in
compliance with Winnforum specification.
Extension of this tool may be required for a complete and proper analysis and in any
case engineering due diligence is still required before drawing meaningful conclusions.



Standard Simulator
==============================
This mode is selected when no "--log_file" option.

Under this mode it performs 2 type of analysis:

1. Standard single worst-case analysis (always).

Performs a "worst-case" interference check, and generates all related disk logs.
Because it looks at worst case, the SAS UUT is assumed to be a ref_model-like
move list algorithm providing the smallest move list (ie the most optimal one).
The 'ref model' move list can be chosen to be the biggest move list (default),
the median size move list or a composite "intersection based" move list.

2. Extensive interference analysis (optional with --do_extensive)

Performs many interference check without logs, and create scatter plots
analysing the required linear margin.
In that mode, the UUT move list is compared against each of the synthesized
ref move list, and all individual interference check displayed in scatter plots
and histogram.


Example simulation:
------------------
  python dpa_margin_sim.py --num_process=3 --num_ml 20 --dpa West14  \
                           --dpa_builder "default(18,0,0,0)" \
                           --dpa_builder_uut "default(25,0,0,0)" \
                           --do_extensive \
                           --uut_ml_method min --uut_ml_num 10 \
                            data/ipr7_1kCBSDs.config
  : Extensive simulation, on West14, with higher number of protected points in
    UUT (UUT is best move list of 10), while reference move list spans all
    20 randomly generated ones.


Test Harness Log Analyzer
===============================
This mode is entered when specifying the "--log_file" option.

Performs the analysis of results obtained during a test exercising the
DPA interference check.
Plots the move list and keep list of the SAS UUT versus reference models. Also
creates scatter and CDF plots of UUT vs reference margin for 3 types of analysis:

1. The reference move list versus the SAS UUT move list (ie as obtained during the test):

This is done by repeating many times the CheckInterference test and analyzing the
results variability and test success/failure caused by the Monte Carlo randomness
during that CheckInterference procedure.
If the original test has failed, but this check shows a small failure rate, this
original failure is most likely a false negative, just caused by the particular
Monte Carlo random draw.

2. Many newly generated reference move list versus the SAS UUT move list:

This is done by regenerating many reference move list (--num_ml), and then
analysing the failure/success statistics of each one of those versus the SAS UUT
move list.
This goes further from case 1, as it can detect "bad luck" scenarios where the
reference move list is not statistically representative.

3. Many newly generated reference move list versus a best case SAS UUT move list:

Similar to 2), but the SAS UUT move list is now generated by taking the smallest
size reference move list. This allows to get some hints when a SAS UUT move list
procedure seems to differ significantly from the Winnforum spec.

Note: Analysis 2 and 3 are only performed in `--do_extensive`  option. In that case
a direct plot of the best case UUT versus real UUT is also provided in terms of
statistical behavior in terms of required margin.


Example analysis
------------------
  python dpa_margin_sim.py \
         --num_process=3 --num_ml 100 --do_extensive \
         --log="output/2018-11-14 13_05_16 DPA=West14 channel=(3620.0, 3630.0) (neighbor list).csv" \
         data/ipr5_5kCBSDs.config

  : Analysis of log files of a test.
    Internal statistical analysis will use 100 different regenerated ref move lists.


Notes on modeling capabilties:
===================================
By default will use the exact configuration of the json file for DPA. However
this can be overriden using some options:
  --dpa <dpa_name>: specify an alternative DPA to use from the standard E-DPA/P-DPA KMLs.
  --dpa_builder <"default(18,0,0,0,0)">: an alternative protected points builder.
   Required if using --dpa option
  --dpa_builder_uut <"default(25,0,0,0,0)">: an alternative builder for UUT only.
   This is to further simulate a different UUT implementation using different
   protected points.

Note that --dpa and --dpa_builder are required if using a grant-only config file.


Other parameters:
-----------------
  --num_ml <10>: number of internal move list for variability analysing.
  --ref_ml_method <method>: method used to generate the reference move list:
      'min': use the minimum size move list
      'max': use the maximum size move list
      'med' or 'median': use the median size move list
      'inter' or 'intersect': use the intersection of move lists (NIST method)
  --ref_ml_num <num>: number of move lists to consider in above method. If 0,
    then use --num_ml
  --uut_ml_method and --uut_ml_num: same for UUT.
  --do_extensive: extensive variability analysis mode. Produces advanced scatter
    plots of UUT versus reference interference (across points and azimuth).

Misc notes:
-----------
  - multiprocessing facility not tested on Windows. Use single process if experiencing
    issues: `-num_process 1`.
  - if warning reported on cached tiles swapping, increase the cache size with
    option `--size_tile_cache XX`.
  - use --seed <1234>: to specify a new random seed.
  - in simulation mode, use --cache_file <filename>: to generate a pickled file
  containing the DPA and move lists (as a tuple). This allows to reload this later
  and rerun detailed analysis with different parameters in interactive sessions
  (advanced use only).
"""
from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import argparse
import copy
from six.moves import cPickle
import logging
import sys
import time

from absl import app
import matplotlib.pyplot as plt
import numpy as np
import shapely.geometry as sgeo
from six.moves import range

from reference_models.common import mpool
from reference_models.dpa import dpa_mgr
from reference_models.dpa import dpa_builder
from reference_models.dpa import move_list as ml
from reference_models.geo import drive
from reference_models.geo import zones
from reference_models.tools import sim_utils

# Utility functions
Db2Lin = dpa_mgr.Db2Lin
Lin2Db = dpa_mgr.Lin2Db

#----------------------------------------
# Setup the command line arguments
parser = argparse.ArgumentParser(description='DPA Simulator')
# - Generic config.
parser.add_argument('--seed', type=int, default=12, help='Random seed.')
parser.add_argument('--num_process', type=int, default=-1,
                    help='Number of parallel process. -2=all-1, -1=50%.')
parser.add_argument('--size_tile_cache', type=int, default=40,
                    help='Number of parallel process. -2=all-1, -1=50%.')
parser.add_argument('--log_level', type=str, default='info',
                    help='Logging level: debug, info, warning, error.')
# - DPA configuration
parser.add_argument('--dpa', type=str, default='',
                    help='Optional: override DPA to consider. Needs to specify '
                    'also the --dpa_builder')
parser.add_argument('--dpa_builder', type=str, default='',
                    help='Optional: override DPA builder to use '
                    'for generating DPA protected points. See BuildDpa().')
parser.add_argument('--dpa_builder_uut', type=str, default='',
                    help='Optional: override DPA builder to use '
                    'for generating DPA protected points for UUT.')
parser.add_argument('--dpa_kml', type=str, default='',
                    help='Optional: override DPA KML (use with --dpa only).')
parser.add_argument('--margin_db', type=str, default='',
                    help='Optional: override `movelistMargin`, for ex:`linear(1.5)`.')
parser.add_argument('--channel_freq_mhz', type=int, default=0,
                    help='Optional: the channel frequency to analyze (lower freq).')
# - Move list building methods
parser.add_argument('--ref_ml_method', type=str, default='max',
                    help='Method of reference move list: '
                    '`max`: max size move list, `med`: median size move list, '
                    '`min`: min size move list, `inter`: intersection of move lists')
parser.add_argument('--ref_ml_num', type=int, default=0,
                    help='Number of move list to use in --ref_ml_method.'
                    '0 means all, otherwise the specified number.')
parser.add_argument('--uut_ml_method', type=str, default='min',
                    help='Method of UUT move list: '
                    '`max`: max size move list, `med`: median size move list, '
                    '`min`: min size move list, `inter`: intersection of move lists')
parser.add_argument('--uut_ml_num', type=int, default=0,
                    help='Number of move list to use in --uut_ml_method.'
                    '0 means all, otherwise the specified number.')
# - Simulation/Analyzis parameters
parser.add_argument('--do_extensive', action='store_true',
                    help='Do extensive aggregate interference analysis '
                    'by checking all possible ref move list')
parser.add_argument('--num_ml', type=int, default=100,
                    help='Number of move list to compute.')
parser.add_argument('--cache_file', type=str, default='',
                    help='If defined, save simulation data to file. '
                    'Allows to rerun later detailed analysis')
parser.add_argument('config_file', type=str, default='',
                    help='The configuration file (IPR or MCP)')

# - Analyze mode
parser.add_argument('--log_file', type=str, default='',
                    help='The configuration file (IPR or MCP)')


_LOGGER_MAP = {
    'info': logging.INFO,
    'debug': logging.DEBUG,
    'warning': logging.WARNING,
    'error': logging.ERROR
}

# Simulation data saved to cache file when using --cache-file
def SaveDataToCache(cache_file, sim_data):
  """Save simulation data to pickled file."""
  with open(cache_file, 'w') as fd:
    cPickle.dump(sim_data, fd)
  print('Simulation data saved to %s' % cache_file)


def SyntheticMoveList(ml_list, method, num, chan_idx):
  """Gets a synthetic move list from a list of them according to some criteria.

  See options `ref_ml_method` and `ref_ml_num`.
  """
  if num == 0: num = len(ml_list)
  ml_size = [len(ml[chan_idx]) for ml in ml_list]
  if method.startswith('med'):
    # Median method (median size keep list)
    median_idx = ml_size.index(np.percentile(ml_size[:num], 50,
                                             interpolation='nearest'))
    ref_ml = ml_list[median_idx]
  elif method.startswith('max'):
    # Max method (bigger move list, ie smallest keep list).
    max_idx = np.argmax(ml_size[:num])
    ref_ml = ml_list[max_idx]
  elif method.startswith('min'):
    # Min method (smaller move list, ie bigger keep list).
    min_idx = np.argmin(ml_size[:num])
    ref_ml = ml_list[min_idx]
  elif method.startswith('int'):
    # Intersection method (similar to method of Michael Souryal - NIST).
    # One difference is that we do not remove xx% of extrema.
    ref_ml = []
    for chan in range(len(ml_list[0])):
      ref_ml.append(set.intersection(*[ml_list[k][chan]
                                       for k in range(num)]))
  elif method.startswith('idx'):
    idx = int(method.split('idx')[1])
    ref_ml = ml_list[idx]
  else:
    raise ValueError('Ref ML method %d unsupported' % method)
  return ref_ml

def ScatterAnalyze(ref_levels, diff_levels, threshold_db, tag):
  """Plots scatter graph of interference variation."""
  if not ref_levels: return
  ref_levels, diff_levels = np.asarray(ref_levels), np.asarray(diff_levels)
  # Find the maximum variation in mW
  diff_mw = Db2Lin(ref_levels + diff_levels) - Db2Lin(ref_levels)
  max_diff_mw = np.max(diff_mw)
  max_margin_db = Lin2Db(max_diff_mw + Db2Lin(threshold_db)) - threshold_db
  print('Max difference: %g mw ==> %.3fdB (norm to %.0fdBm)' % (
      max_diff_mw, max_margin_db, threshold_db))
  print('Statistics: ')
  max_diff_1_5 = Db2Lin(threshold_db + 1.5) - Db2Lin(threshold_db)
  print('  < 1.5dB norm: %.4f%%' % (
      np.count_nonzero(diff_mw < Db2Lin(threshold_db+1.5)-Db2Lin(threshold_db))
      / float(len(diff_mw)) * 100.))
  print('  < 2.0dB norm: %.4f%%' % (
      np.count_nonzero(diff_mw < Db2Lin(threshold_db+2.0)-Db2Lin(threshold_db))
      / float(len(diff_mw)) * 100.))
  print('  < 2.5dB norm: %.4f%%' % (
      np.count_nonzero(diff_mw < Db2Lin(threshold_db+2.5)-Db2Lin(threshold_db))
      / float(len(diff_mw)) * 100.))
  print('  < 3.0dB norm: %.4f%%' % (
      np.count_nonzero(diff_mw < Db2Lin(threshold_db+3.0)-Db2Lin(threshold_db))
      / float(len(diff_mw)) * 100.))
  print('  < 3.5dB norm: %.4f%%' % (
      np.count_nonzero(diff_mw < Db2Lin(threshold_db+3.5)-Db2Lin(threshold_db))
      / float(len(diff_mw)) * 100.))

  # Plot the scatter plot
  plt.figure()
  plt.suptitle('Aggr Interf Delta - %s' % tag)

  plt.subplot(211)
  plt.grid(True)
  plt.xlabel('Reference aggregate interference (dBm/10MHz)')
  plt.ylabel('SAS UUT difference (dB)')
  plt.scatter(ref_levels, diff_levels, c = 'r', marker='.', s=10)
  margin_mw = Db2Lin(threshold_db + 1.5) - Db2Lin(threshold_db)
  x_data = np.arange(min(ref_levels), max(ref_levels), 0.01)
  plt.plot(x_data, Lin2Db(Db2Lin(x_data) + margin_mw) - x_data, 'b',
           label='Fixed Linear Margin @1.5dB')
  plt.plot(x_data, Lin2Db(Db2Lin(x_data) + max_diff_mw) - x_data, 'g',
           label='Fixed Linear Margin @%.3fdB' % max_margin_db)
  plt.legend()

  plt.subplot(212)
  margins_db = Lin2Db(diff_mw + Db2Lin(threshold_db)) - threshold_db
  plt.grid(True)
  plt.ylabel('Complement Log-CDF')
  plt.xlabel('SAS UUT Normalized diff (dB to %ddBm)' % threshold_db)
  sorted_margins_db = np.sort(margins_db)
  sorted_margins_db = sorted_margins_db[sorted_margins_db > -5]
  y_val = 1 - np.arange(len(margins_db), dtype=float) / len(margins_db)
  if len(sorted_margins_db):
    plt.plot(sorted_margins_db, y_val[-len(sorted_margins_db):])
  plt.yscale('log', nonposy='clip')


def ExtensiveInterferenceCheck(dpa,
                               uut_keep_list, ref_move_lists,
                               ref_ml_num, ref_ml_method,
                               channel, chan_idx, tag=''):
  """Performs extensive interference check of UUT vs many reference move lists.

  Args:
    dpa: A reference |dpa_mgr.Dpa|.
    uut_keep_list: The UUT keep list for the given channel.
    ref_move_lists: A list of reference move lists.
    ref_ml_num & ref_ml_method: The method for building the reference move list
      used for interference check. See module documentation.
    channel & chan_idx: The channels info.

  Returns:
    A tuple of 2 lists (ref_level, diff_levels) holding all the interference
    results over each points, each azimuth and each synthesized reference move list.
  """
  num_success = 0
  ref_levels = []
  diff_levels = []
  start_time = time.time()
  num_synth_ml = 1 if not ref_ml_num else ref_ml_num
  num_check = len(ref_move_lists) - num_synth_ml + 1
  for k in range(num_check):
    dpa.move_lists = SyntheticMoveList(ref_move_lists[k:],
                                       ref_ml_method, ref_ml_num,
                                       chan_idx)
    interf_results = []
    num_success += dpa.CheckInterference(uut_keep_list, dpa.margin_db,
                                         channel=channel,
                                         extensive_print=False,
                                         output_data=interf_results)
    sys.stdout.write('.'); sys.stdout.flush()
    for pt_res in interf_results:
      if not pt_res.A_DPA_ref.shape: continue
      ref_levels.extend(pt_res.A_DPA_ref)
      diff_levels.extend(pt_res.A_DPA - pt_res.A_DPA_ref)

  print('   Computation time: %.1fs' % (time.time() - start_time))
  print('Extensive Interference Check:  %d success / %d (%.3f%%)' % (
      num_success, num_check, (100. * num_success) / num_check))
  if not ref_levels:
    print('Empty interference - Please check your setup')

  ScatterAnalyze(ref_levels, diff_levels, dpa.threshold,
                 tag + 'DPA: %s' % dpa.name)
  return np.asarray(ref_levels), np.asarray(diff_levels)


def PlotMoveListHistogram(move_lists, chan_idx):
  """Plots an histogram of move lists size."""
  ref_ml_size = [len(ml[chan_idx]) for ml in move_lists]
  plt.figure()
  plt.hist(ref_ml_size)
  plt.grid(True)
  plt.xlabel('Count')
  plt.ylabel('')
  plt.title('Histogram of move list size across %d runs' % len(ref_ml_size))

def GetMostUsedChannel(dpa):
  """Gets the (channel, chan_idx) of the most used channel in |dpa_mgr.Dpa|."""
  chan_idx = np.argmax([len(dpa.GetNeighborList(chan)) for chan in dpa._channels])
  channel = dpa._channels[chan_idx]
  return channel, chan_idx


def FindOrBuildDpa(dpas, options, grants):
  """Find or build DPA for simulation purpose.

  If several DPA, select the one with most grants around (but DPA simulation
  options always override the logic).
  """
  if options.dpa:
    dpa_kml_file = options.dpa_kml or None
    dpa = None
    if dpas:
      for d in dpas:
        if d.name.lower() == options.dpa.lower():
          dpa = d
          break
    if not dpa:
      print('Cannot find DPA in config - creating a default one')
      dpa = dpa_mgr.BuildDpa(options.dpa, None, portal_dpa_filename=dpa_kml_file)
  else:
    if not dpas:
      raise ValueError('Config file not defining a DPA and no --dpa option used.')
    if len(dpas) == 1:
      dpa = dpas[0]
    else:
      # Roughly find the DPA wth most CBSD within 200km
      all_cbsds = sgeo.MultiPoint([(g.longitude, g.latitude) for g in grants])
      num_cbsds_inside = [len(dpa.geometry.buffer(2.5).intersection(all_cbsds))
                          for dpa in dpas]
      dpa = dpas[np.argmax(num_cbsds_inside)]

  try: dpa.margin_db
  except AttributeError:
    dpa.margin_db = 'linear(1.5)'
  try: dpa.geometry
  except AttributeError:
    try: dpa_geometry = zones.GetCoastalDpaZones()[dpa.name]
    except KeyError: dpa_geometry = zones.GetPortalDpaZones(kml_path=dpa_kml_file)[dpa.name]
    dpa.geometry = dpa_geometry.geometry
  if options.dpa_builder:
    dpa.protected_points = dpa_builder.DpaProtectionPoints(
        dpa.name, dpa.geometry, options.dpa_builder)
  if options.margin_db:  # Override `movelistMargin` directive.
    try: dpa.margin_db = float(options.margin_db)
    except ValueError: dpa.margin_db = options.margin_db

  return dpa

def SetupSimProcessor(num_process, size_tile_cache, geo_points, load_cache=False):
  print('== Setup simulator resources - loading all terrain tiles..')
  # Make sure terrain tiles loaded in main process memory.
  # Then forking will make sure worker reuse those from shared memory (instead of
  # reallocating and reloading the tiles) on copy-on-write system (Linux).
  # TODO(sbdt): review this as it does not seem to really work.
  # - disable workers
  if load_cache:
    num_workers = sim_utils.ConfigureRunningEnv(
        num_process=0, size_tile_cache=size_tile_cache)
    # - read some altitudes just to load the terrain tiles in main process memory
    junk_alt = drive.terrain_driver.GetTerrainElevation(
        [g.latitude for g in geo_points], [g.longitude for g in geo_points],
        do_interp=False)
  # - enable the workers
  num_workers = sim_utils.ConfigureRunningEnv(
      num_process=options.num_process, size_tile_cache=size_tile_cache)
  if load_cache:
    # Check cache is ok
    sim_utils.CheckTerrainTileCacheOk()  # Cache analysis and report
  time.sleep(1)
  return num_workers

#----------------------------------------------
# Utility routines for re-analyse from cache pickle dumps (advanced mode only).
# Usage:
#  import dpa_margin_sim as dms
#  sim_utils.ConfigureRunningEnv(-1, 40)
#  sim_data = LoadDataFromCache(cache_file)
#  CacheAnalyze(sim_data, 'max', 1, 'min', 100)
def LoadDataFromCache(cache_file):
  """Load simulation data from pickled file."""
  with open(cache_file, 'r') as fd:
    return cPickle.load(fd)

def CacheAnalyze(sim_data,
                 ref_ml_method, ref_ml_num,
                 uut_ml_method, uut_ml_num):
  """Extensive analyze from loaded simulation data. See module doc."""
  dpa_ref = sim_data[0]
  dpa_uut = sim_data[2]
  channel, chan_idx = GetMostUsedChannel(dpa_ref)
  dpa_uut.move_lists = SyntheticMoveList(sim_data[3],
                                         uut_ml_method, uut_ml_num,
                                         chan_idx)
  uut_keep_list = dpa_uut.GetKeepList(channel)
  ExtensiveInterferenceCheck(dpa_ref, uut_keep_list,
                             sim_data[1],
                             ref_ml_num, ref_ml_method,
                             channel, chan_idx)
  plt.show(block=False)


#-----------------------------------------------------
# DPA aggregate interference variation simulator
def DpaSimulate(config_file, options):
  """Performs the DPA simulation."""
  if options.seed is not None:
    # reset the random seed
    np.random.seed(options.seed)

  logging.getLogger().setLevel(logging.WARNING)

  # Read the input config file into ref model entities.
  grants, dpas = sim_utils.ReadTestHarnessConfigFile(config_file)
  # Select appropriate DPA or buid one from options.
  dpa = FindOrBuildDpa(dpas, options, grants)

  # Setup the simulator processor: number of processor and cache.
  num_workers = SetupSimProcessor(options.num_process, options.size_tile_cache,
                                  grants)

  # Simulation start
  print('Simulation with DPA `%s` (ref: %d pts):\n'
        '  %d granted CBSDs: %d CatB - %d CatA_out - %d CatA_in' % (
         dpa.name, len(dpa.protected_points),
         len(grants),
         len([grant for grant in grants if grant.cbsd_category == 'B']),
         len([grant for grant in grants
              if grant.cbsd_category == 'A' and not grant.indoor_deployment]),
         len([grant for grant in grants
              if grant.cbsd_category == 'A' and grant.indoor_deployment])))

  # Plot the entities.
  ax, _ = sim_utils.CreateCbrsPlot(grants, dpa=dpa)
  plt.show(block=False)

  # Set the grants into DPA.
  dpa.SetGrantsFromList(grants)

  # Manages the number of move list to compute.
  if options.dpa_builder_uut == options.dpa_builder:
    options.dpa_builder_uut = ''
  num_ref_ml = options.ref_ml_num or options.num_ml
  num_uut_ml = options.uut_ml_num or options.num_ml
  num_base_ml = (num_ref_ml if options.dpa_builder_uut
                 else max(num_ref_ml, num_uut_ml))
  if options.do_extensive:
    num_base_ml = max(num_base_ml, options.num_ml)

  # Run the move list N times on ref DPA
  print('Running Move List algorithm (%d workers): %d times' % (
      num_workers, num_ref_ml))
  start_time = time.time()
  ref_move_list_runs = []  # Save the move list of each run
  for k in range(num_base_ml):
    dpa.ComputeMoveLists()
    ref_move_list_runs.append(copy.copy(dpa.move_lists))
    sys.stdout.write('.'); sys.stdout.flush()

  # Plot the last move list on map.
  for channel in dpa._channels:
    move_list = dpa.GetMoveList(channel)
    sim_utils.PlotGrants(ax, move_list, color='r')

  # Now build the UUT dpa and move lists
  dpa_uut = copy.copy(dpa)
  uut_move_list_runs = ref_move_list_runs[:num_uut_ml]
  if options.dpa_builder_uut:
    dpa_uut.protected_points = dpa_builder.DpaProtectionPoints(
        dpa_uut.name, dpa_uut.geometry, options.dpa_builder_uut)
    # If UUT has its own parameters, simulate it by running it,
    # otherwise reuse the move lists of the ref model.
    uut_move_list_runs = []
    for k in range(num_uut_ml):
      dpa_uut.ComputeMoveLists()
      uut_move_list_runs.append(copy.copy(dpa_uut.move_lists))
      sys.stdout.write('+'); sys.stdout.flush()

  ref_move_list_runs = ref_move_list_runs[:num_ref_ml]
  print('\n   Computation time: %.1fs' % (time.time() - start_time))

  # Save data
  if options.cache_file:
    SaveDataToCache(options.cache_file,
                    (dpa, ref_move_list_runs,
                     dpa_uut, uut_move_list_runs,
                     options))

  # Find a good channel to check: the one with maximum CBSDs.
  channel, chan_idx = GetMostUsedChannel(dpa)
  # Plot the move list sizes histogram for that channel.
  PlotMoveListHistogram(ref_move_list_runs, chan_idx)

  # Analyze aggregate interference. By default:
  #   + uut: taking smallest move list (ie bigger keep list)
  #   + ref: taking biggest move list (ie smallest keep list)
  #      or  taking a median or intersection move list
  # Hopefully (!) this is a good proxy for worst case scenarios.
  #
  #  - enable log level - usually 'info' allows concise report.
  logging.getLogger().setLevel(_LOGGER_MAP[options.log_level])
  # - The ref case first
  dpa.move_lists = SyntheticMoveList(ref_move_list_runs,
                                     options.ref_ml_method, options.ref_ml_num,
                                     chan_idx)

  # - The UUT case
  dpa_uut.move_lists = SyntheticMoveList(uut_move_list_runs,
                                         options.uut_ml_method, options.uut_ml_num,
                                         chan_idx)
  uut_keep_list = dpa_uut.GetKeepList(channel)

  start_time = time.time()
  print('*****  BASIC INTERFERENCE CHECK: size ref_ML=%d vs %d *****' % (
      len(dpa.move_lists[chan_idx]), len(dpa_uut.move_lists[chan_idx])))

  success = dpa.CheckInterference(uut_keep_list, dpa.margin_db, channel=channel,
                                  extensive_print=True)
  print('   Computation time: %.1fs' % (time.time() - start_time))

  # Note: disable extensive logging for further extensive interference check
  logging.getLogger().setLevel(logging.ERROR)

  # Extensive mode: compare UUT against many ref model move list
  if options.do_extensive:
    print('*****  EXTENSIVE INTERFERENCE CHECK *****')
    ExtensiveInterferenceCheck(dpa, uut_keep_list, ref_move_list_runs,
                               options.ref_ml_num, options.ref_ml_method,
                               channel, chan_idx)
  # Simulation finalization
  print('')
  sim_utils.CheckTerrainTileCacheOk()  # Cache analysis and report


#-----------------------------------------------------
# DPA logs analyzer
def DpaAnalyzeLogs(config_file, log_file, options):
  """Analyze DPA logs through simulation."""
  if options.seed is not None:
    # reset the random seed
    np.random.seed(options.seed)

  logging.getLogger().setLevel(logging.WARNING)

  # Read the input files: config and logs
  if not log_file and config_file:
    log_file = config_file
    config_file = None
  ref_nbor_list, ref_keep_list, uut_keep_list = sim_utils.ReadDpaLogFile(log_file)
  if config_file:
    grants, dpas = sim_utils.ReadTestHarnessConfigFile(config_file)
    # For best robustness, make sure all coordinates are properly rounded, so the
    # 2 sources of data can be exactly compared.
    grants = [sim_utils.CleanGrant(g) for g in grants]
    ref_nbor_list = [sim_utils.CleanGrant(g) for g in ref_nbor_list]
    ref_keep_list = [sim_utils.CleanGrant(g) for g in ref_keep_list]
    uut_keep_list = [sim_utils.CleanGrant(g) for g in uut_keep_list]
  else:
    grants, dpas = ref_nbor_list, []

  ref_nbor_list = set(ref_nbor_list)
  ref_keep_list = set(ref_keep_list)
  uut_keep_list = set(uut_keep_list)
  no_peers = not ref_nbor_list and uut_keep_list
  if no_peers:
    print('NOTE: MCP test with no peer SAS.')
  if options.dpa_builder_uut and options.dpa_builder_uut != options.dpa_builder:
    print(' Option --dpa_builder_uut unsupported in analyze mode: Ignored.')
  if not grants:
    raise ValueError('No grants specified - use a valid config file.')
  # Find reference DPA for analyzis.
  dpa = FindOrBuildDpa(dpas, options, grants)

  # Setup the simulator processor: number of processor and cache.
  num_workers = SetupSimProcessor(options.num_process, options.size_tile_cache,
                                  uut_keep_list)

  # Set the grants into DPA.
  print('== Initialize DPA, one reference move list and misc.')
  print('  Num grants in cfg: %s' % (len(grants) if config_file else 'No Cfg'))
  print('  Num grants in logs: nbor_l=%d  ref_kl_all=%d  uut_kl=%d' % (
      len(ref_nbor_list), len(ref_keep_list), len(uut_keep_list)))
  dpa.SetGrantsFromList(grants)
  if options.channel_freq_mhz:
    dpa.ResetFreqRange([(options.channel_freq_mhz, options.channel_freq_mhz+10)])
  dpa.ComputeMoveLists()

  # Note: disable extensive logging for further extensive interference check.
  logging.getLogger().setLevel(logging.ERROR)

  # Find a good channel to check: the one with maximum CBSDs.
  channel, chan_idx = GetMostUsedChannel(dpa)
  nbor_list = dpa.GetNeighborList(channel)
  move_list = dpa.GetMoveList(channel)
  keep_list = dpa.GetKeepList(channel)
  print('  DPA for analyze:  %s' % dpa.name)
  print('  Channel for analyze: %s' % (channel,))
  print('  Recalc on chan: nbor_l=%d kl=%d' % (len(nbor_list), len(keep_list)))
  # Initial step - plot CBSD on maps: UUT keep list vs ref model keep list
  print('== Plot relevant lists on map.')
  # Plot the entities.
  print('  Plotting Map: Nbor list and keep list for channel %s' % (channel,))
  uut_move_list_uut = [g for g in nbor_list
                       if g.is_managed_grant and g not in uut_keep_list]
  move_list_uut = [g for g in move_list if g.is_managed_grant]
  move_list_other = [g for g in move_list if not g.is_managed_grant]

  if len(ref_nbor_list):
    ref_move_list = nbor_list.difference(ref_keep_list)
    ref_move_list_uut = [g for g in ref_move_list if g.is_managed_grant]
    ref_move_list_other = [g for g in ref_move_list if not g.is_managed_grant]
    ax1, fig = sim_utils.CreateCbrsPlot(nbor_list, dpa=dpa, tag='Test Ref ', subplot=121)
    sim_utils.PlotGrants(ax1, ref_move_list_other, color='m')
    sim_utils.PlotGrants(ax1, ref_move_list_uut, color='r')
    ax2, _ = sim_utils.CreateCbrsPlot(nbor_list, dpa=dpa, tag='Test UUT ', subplot=122, fig=fig)
    sim_utils.PlotGrants(ax2, ref_move_list_other, color='m')
    sim_utils.PlotGrants(ax2, uut_move_list_uut, color='r')
    fig.suptitle('Neighbor and move list from Test Log - Chan %s' % (channel,))

  ax1, fig = sim_utils.CreateCbrsPlot(nbor_list, dpa=dpa, tag='Calc Ref ', subplot=121)
  sim_utils.PlotGrants(ax1, move_list_other, color='m')
  sim_utils.PlotGrants(ax1, move_list_uut, color='r')
  ax2, _ = sim_utils.CreateCbrsPlot(nbor_list, dpa=dpa, tag='Test UUT ', subplot=122, fig=fig)
  sim_utils.PlotGrants(ax2, ref_move_list_other, color='m')
  sim_utils.PlotGrants(ax2, uut_move_list_uut, color='r')
  fig.suptitle('Neighbor and move list from Calc + UUT Log - Chan %s' % (channel,))
  plt.show(block=False)

  # Manages the number of move list to compute.
  num_ref_ml = options.ref_ml_num or options.num_ml
  num_uut_ml = options.num_ml
  num_base_ml = max(num_ref_ml, num_uut_ml)

  # Summary of the analyze.
  print('== Analysing DPA `%s` (ref: %d pts) on Channel %s:\n'
        '  %d total grants (all channels)\n'
        '  %d CBSDs in neighbor list: %d CatB - %d CatA_out - %d CatA_in\n' % (
         dpa.name, len(dpa.protected_points), channel,
         len(grants),
         len(nbor_list),
         len([grant for grant in nbor_list if grant.cbsd_category == 'B']),
         len([grant for grant in nbor_list
              if grant.cbsd_category == 'A' and not grant.indoor_deployment]),
         len([grant for grant in nbor_list
              if grant.cbsd_category == 'A' and grant.indoor_deployment])))

  # Analyze aggregate interference of TEST-REF vs SAS_UUT keep list
  # ie we repeat the Check N times but with the same ML
  if len(ref_nbor_list):
    start_time = time.time()
    num_check = max(10, num_base_ml // 2)
    print('*****  Re-testing REAL SAS UUT vs %d TEST-REF move list *****' % (num_check))
    print('  Same ref move list each time from TEST - only interference check is random. ')
    full_ref_move_list_runs = [None] * len(dpa._channels)
    full_ref_move_list_runs[chan_idx] = nbor_list.difference(ref_keep_list)
    many_ref_move_list_runs = [full_ref_move_list_runs] * num_check
    ExtensiveInterferenceCheck(dpa, uut_keep_list, many_ref_move_list_runs,
                               1, 'max', channel, chan_idx,
                               tag='REAL-REF vs REAL-UUT (%dML) - ' % num_check)
    print('   Computation time: %.1fs' % (time.time() - start_time))

  if not options.do_extensive:
    return

  # Run the move list N times on ref DPA
  print('*****  From now on: analysing against fresh ref move lists *****')
  print('Modes of operation:\n'
        '  UUT ref - Real or best of %d (smallest size)\n'
        '  Against %d different ref move list obtained through method: %s of %d\n' % (
         num_uut_ml, num_ref_ml, options.ref_ml_method, max(options.ref_ml_num, 1)))

  print('First computing %d reference move lists (%d workers)' % (num_ref_ml, num_workers))
  start_time = time.time()
  ref_move_list_runs = []  # Save the move list of each run
  for k in range(num_base_ml):
    dpa.ComputeMoveLists()
    ref_move_list_runs.append(copy.copy(dpa.move_lists))
    sys.stdout.write('.'); sys.stdout.flush()

  # Now build the UUT dpa and move lists
  dpa_uut = copy.copy(dpa)
  uut_move_list_runs = ref_move_list_runs[:num_uut_ml]
  ref_move_list_runs = ref_move_list_runs[:num_ref_ml]
  print('\n   Computation time: %.1fs' % (time.time() - start_time))

  # Save data
  if options.cache_file:
    SaveDataToCache(options.cache_file,
                    (dpa, ref_move_list_runs,
                     dpa_uut, uut_move_list_runs,
                     options))

  # Plot the move list sizes histogram for that channel.
  PlotMoveListHistogram(ref_move_list_runs, chan_idx)

  # Analyze aggregate interference of SAS_UUT keep list vs new reference
  # ie we check the SAS UUT versus many recomputed reference ML
  start_time = time.time()
  print('*****  REAL SAS UUT vs %d random reference move list *****' % num_ref_ml)
  print('  Every ref move list regenerated through move list process (+ %s of %d method)' % (
      options.ref_ml_method, max(options.ref_ml_num, 1)))
  real_levels, real_diffs = ExtensiveInterferenceCheck(
      dpa, uut_keep_list, ref_move_list_runs,
      options.ref_ml_num, options.ref_ml_method,
      channel, chan_idx,
      tag='Rand-Ref vs REAL-UUT (%dML) - ' % num_ref_ml)
  print('   Computation time: %.1fs' % (time.time() - start_time))

  # Analyze aggregate interference of best SAS_UUT keep list vs new reference
  # ie we smallest size ML versus many recomputed reference ML (like in std simulation).
  start_time = time.time()
  print('*****  GOOD SAS UUT vs %d random reference move list *****' % num_ref_ml)
  print('  Every ref move list regenerated through move list process (+ %s of %d method)' % (
      options.ref_ml_method, max(options.ref_ml_num, 1)))
  print('  SAS UUT move list taken with method: %s of %d' % (
      options.uut_ml_method, options.uut_ml_num or len(ref_move_list_runs)))
  dpa_uut.move_lists = SyntheticMoveList(ref_move_list_runs,
                                         options.uut_ml_method, options.uut_ml_num,
                                         chan_idx)
  uut_keep_list = dpa_uut.GetKeepList(channel)
  good_levels, good_diffs = ExtensiveInterferenceCheck(
      dpa, uut_keep_list, ref_move_list_runs,
      options.ref_ml_num, options.ref_ml_method,
      channel, chan_idx,
      tag='Rand-Ref vs Good UUT (%dML) - ' % num_ref_ml)
  print('   Computation time: %.1fs' % (time.time() - start_time))

  # Show on same graph the Real UUT CDF vs Good UUT CDF
  real_diff_mw = Db2Lin(real_levels + real_diffs) - Db2Lin(real_levels)
  real_margins_db = Lin2Db(real_diff_mw + Db2Lin(dpa.threshold)) - dpa.threshold
  sorted_real_margins_db = np.sort(real_margins_db)
  good_diff_mw = Db2Lin(good_levels + good_diffs) - Db2Lin(good_levels)
  good_margins_db = Lin2Db(good_diff_mw + Db2Lin(dpa.threshold)) - dpa.threshold
  sorted_good_margins_db = np.sort(good_margins_db)
  plt.figure()
  plt.title('CDF of Agg Interf Delta: REAL UUT vs GOOD UUT')
  plt.grid(True)
  plt.ylabel('Complement Log-CDF')
  plt.xlabel('SAS UUT Normalized diff (dB to %ddBm)' % dpa.threshold)
  y_val = 1 - np.arange(len(real_levels), dtype=float) / len(real_levels)
  sorted_good_margins_db = sorted_good_margins_db[sorted_good_margins_db > -1]
  sorted_real_margins_db = sorted_real_margins_db[sorted_real_margins_db > -1]
  if len(sorted_good_margins_db):
    plt.plot(sorted_good_margins_db, y_val[-len(sorted_good_margins_db):],
             color='g', label='Good ML')
  if len(sorted_real_margins_db):
    plt.plot(sorted_real_margins_db, y_val[-len(sorted_real_margins_db):],
             color='b', label='Real ML')
  plt.yscale('log', nonposy='clip')
  plt.legend()

#---------------------------
# The simulation
if __name__ == '__main__':
  options = parser.parse_args()
  if options.log_file or options.config_file.endswith('csv'):
    print('Analyzing log files')
    DpaAnalyzeLogs(options.config_file, options.log_file, options)
  else:
    print('Running DPA simulator')
    DpaSimulate(options.config_file, options)
  plt.show(block=True)
