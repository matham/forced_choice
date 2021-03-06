forced_choice Config
====================

:_experiment - default:

`NO_valve`: p0
 A list of, for each block in :attr:`num_blocks`, the normally open
 (mineral oil) odor valve. I.e. the valve which is normally open and closes
 during the trial when the odor is released.
 
`air_rate`: [0]
 A list of, for each block in :attr:`num_blocks`, the flow rate for the
 air stream using the air MFC when :attr:`RootStage.use_mfc` or
 :attr:`RootStage.use_mfc_air`.
 
`bad_iti`: [4]
 The ITI duration of a failed trial.
     
 
`beta_trials_max`: 15
 For each odor, it is the last :attr:`beta_trials_max` trials (of that
 odor) to take into account when computing the accuracy rate for that odor.
 
 Trials for this odor further back in history than :attr:`beta_trials_max`
 specific to this odor are dropped.
 
`beta_trials_min`: 10
 The minimum number of trials for each odor that must have occured before
 :attr:`odor_beta` bias compensation is activated. If the number of trial
 that occurred for any odor is less than :attr:`beta_trials_min`, bias
 compensation is disabled.
 
`good_iti`: [3]
 The ITI duration of a passed trial.
     
 
`incomplete_iti`: [4]
 The ITI duration of a trial where the animal did not hold its nose long
 enough in the nose port and :attr:`min_nose_poke` was not satisfied.
 
`max_decision_duration`: [20.0]
 A list of, for each block in :attr:`num_blocks`, the maximum duration
 of the decision stage. After this duration, the stage will terminate and
 proceed to the ITI stage even if the animal didn't visit the reward port.
 
 The decision determines whether a reward is dispensed and the duration of
 the ITI.
 
 If zero, there is no maximum.
 
`max_nose_poke`: [10.0]
 A list of, for each block in :attr:`num_blocks`, the maximum duration
 of the nose port stage. After this duration, the stage will terminate and
 proceed to the decision stage even if the animal is still in the nose port.
 
 If zero, there is no maximum.
 
`mfc_a_rate`: [0.1]
 A list of, for each block in :attr:`num_blocks`, the flow rate for the
 odor stream a using the odor a MFC when :attr:`RootStage.use_mfc`.
 
`mfc_b_rate`: [0.1]
 A list of, for each block in :attr:`num_blocks`, the flow rate for the
 odor stream b using the odor b MFC when :attr:`RootStage.use_mfc`.
 
`min_nose_poke`: [0]
 A list of, for each block in :attr:`num_blocks`, the minimum duration
 in the nose port AFTER the odor is released (i.e. :attr:`odor_delay`).
 A nose port exit less than this duration will result in an incomplete
 trial. The ITI will then be :attr:`incomplete_iti`.
 
 If zero, there is no minimum.
 
`mix_dur`: 1.5
 A list of, for each block in :attr:`num_blocks`, how long to pass the
 air stream through the odor vials before the trial starts (during
 the last ITI).
 
 This ensures that when the animal enters the nose port, the odor is stream
 is already saturated. During this time the odor is directed to teh vaccum.
 
`mix_valve`: p7
 A list of, for each block in :attr:`num_blocks`, the valve that directs
 the odor to go to vacuum or to the animal. Before the odor goes to the
 animal, the odor is mixed and evacuated to vacuum in order to saturate the
 air stream into a steady state condition.
 
`num_blocks`: 3
 The number of blocks to run. Each block runs :attr:`num_trials` trials.
 
 All the configuration parameters that are lists, e.g. :attr:`num_trials`
 can specify a different value for each block.
 
 If the number of elements in these lists are less than the number of
 blocks, the last value of the list is used for the remaining blocks. E.g.
 for 10 blocks, if :attr:`num_trials` is ``[5, 6, 2]``, then blocks 2 - 9
 will have 2 trials.
 
`num_pellets`: [2]
 The number of sugar pellets to deliver upon a successful trial.
     
 
`num_trials`: [10]
 A list of the number of trials to run for each block of
 :attr:`num_blocks`.
 
`odor_beta`: [0]
 A list of, for each block in :attr:`num_blocks`, the beta value to use
 when compensating for unequal side performance. This compensation is
 applied dynamically during the trials on top of any previous odor
 computations.
 
 We keep track of the accuracy rate of every odor (i.e. how often the animal
 chooses the incorrectly for that odor). Then, odors where the animal
 performed poorly will get presented with a higher probability.
 
 A :attr:`odor_beta` value of zero disables this bias compensation. A value
 of e.g. 10, will bias very strongly towards changing the next trial odor
 to be a odor in which the animal performed poorly. The closer to zero, the
 lower such bias compensation. A value of 2-3 is reasonable.
 
 The trials are accumulated across blocks so a new block does not clear the
 odor bias history.
 
`odor_delay`: [0]
 A list of, for each block in :attr:`num_blocks`, how long to delay the
 odor delivery onset from when the animal enters the nose port.
 
 If zero, there's no delay.
 
`odor_equalizer`: [6, 8]
 A list of, for each block in :attr:`num_blocks`, the number of trials
 during which all the odors for that block will be presented an equal
 number of times.
 
 That is, during these exclusively grouped :attr:`odor_equalizer` trials,
 no odor will be presented more times than any other odor.
 
 The number of odors for each block listed in :attr:`odor_selection` must
 divide without remainder the :attr:`odor_equalizer` value for that block.
 
`odor_method`: ['constant', 'random2']
 A list of, for each block in :attr:`num_blocks`, the method used to
 determine which odor to use in the trials for the odors listed in
 :attr:`odor_selection`.
 
 Possible methods are `constant`, `randomx`, or `list`.
 :attr:`odor_selection` is used to select the odor to be used with this
 method.
 
     `constant`:
         :attr:`odor_selection` is a 2d list of odors of length
         :attr:`num_blocks`. Each element in the outer list is a single
         element list containing the odor that is used for all the trials of
         that block.
     `randomx`: x is a number or empty
         :attr:`odor_selection` is a 2d list of odors of length
         :attr:`num_blocks`. Each inner list is a list of odors from which
         the trial odor would be randomly selected for each trial in the
         block.
 
         If the method is ``random``, the odor is randomly selected
         from that list. If random is followed by an integer, e.g.
         ``random2``, then it's random with the condition that no odor can
         be repeated more then x (2 in this) times successively.
     `list`:
         :attr:`odor_selection` is a 2d list of filenames. The files are
         read for each block and the odors listed in the file is used for
         the trials.
 
         The structure of the text file is a line for each block. Each line
         is a comma separated list, with the first column being the block
         number and the other column the odors to use for that block.
 
         Each inner list in the 2d list (line) can only have a
         single filename for that block.
 
`odor_path`: odor_list.txt
 The filename of a file containing the names of odors and which side to
 reward that odor.
 
 The structure of the file is as follows: each line
 describes an odor and is a 3 or 4 column comma separated list of
 ``(idx, name, side, mfc)``, where idx is the zero-based valve index.
 Name is the odor name. And side is the side of the odor to reward
 (r, l, rl, lr, or -).
 If using an mfc, the 4th column is either ``a``, or ``b`` indicating the
 mfc to use of that valve.
 
 An example file is::
 
     1, mineral oil, r
     4, citric acid, rl
     5, limonene, l
     ...
 
`odor_selection`: [['p1'], ['p1', 'p2']]
 A list of, for each block in :attr:`num_blocks`, a inner list of odors
 used to select from trial odors for each block. See :attr:`odor_method`.
 
`sound_cue_delay`: [0]
 A list of, for each block in :attr:`num_blocks`, the random amount
 of time to delay the sound cue AFTER :attr:`min_nose_poke` elapsed. It's
 a value between zero and :attr:`sound_cue_delay`.
 
 If zero or if :attr:`sound_dur` is zero, there is no delay.
 
`sound_dur`: [0]
 A list of, for each block in :attr:`num_blocks`, the duration to play
 the sound cue after :attr:`sound_cue_delay`. It plays either
 :attr:`RootStage.sound_file_r` or :attr:`RootStage.sound_file_l` depending
 on the trial odor.
 
 If zero, no sound is played.
 
`wait_for_nose_poke`: [False, True]
 A list of, for each block in :attr:`num_blocks`, whether to wait for a
 nose poke or to immediately go to the reward stage.
 
 When False, entering the reward port will dispense reward and end the
 trial. The ITI will then be :attr:`good_iti` for that block.
 

:app:

`inspect`: False
 Enables GUI inspection. If True, it is activated by hitting ctrl-e in
 the GUI.
 

:barst_server:

`server_path`: 
 The full path to the Barst executable. Could be empty if the server
 is already started, on remote computer, or if it's in the typical
 `Program Files` path or came installed with the wheel. If the server is not
 running, this executable is needed to launch the server.
 
 Defaults to `''`.
 
`server_pipe`: 
 The full path to the pipe name (to be) used by the server. Examples are
 ``\remote_name\pipe\pipe_name``, where ``remote_name`` is the name of
 the remote computer, or a period (`.`) if the server is local, and
 ``pipe_name`` is the name of the pipe used to create the server.
 
 Defaults to `''`.
 

:daqin:

`SAS_chan`: 0
 The channel number of the Switch & Sense 8/8 as configured in InstaCal.
 
 Defaults to zero.
 
`nose_beam_pin`: 1
 The port in the Switch & Sense to which the nose port photobeam is
 connected to.
 
 Defaults to 1.
 
`reward_beam_l_pin`: 2
 The port in the Switch & Sense to which the left reward port photobeam
 is connected to.
 
 Defaults to 2.
 
`reward_beam_r_pin`: 3
 The port in the Switch & Sense to which the right reward port photobeam
 is connected to.
 
 Defaults to 3.
 

:daqout:

`SAS_chan`: 0
 The channel number of the Switch & Sense 8/8 as configured in InstaCal.
 
 Defaults to zero.
 
`fans_pin`: 5
 The port in the Switch & Sense that controls the fans.
 
 Defaults to 5.
 
`feeder_l_pin`: 0
 The port in the Switch & Sense that controls the left feeder.
 
 Defaults to 0.
 
`feeder_r_pin`: 2
 The port in the Switch & Sense that controls the right feeder.
 
 Defaults to 2.
 
`house_light_pin`: 4
 The port in the Switch & Sense that controls the house light.
 
 Defaults to 4.
 
`ir_leds_pin`: 6
 The port in the Switch & Sense that controls the IR lights.
 
 Defaults to 6.
 

:devices:

`filter_len`: 1
 The number of previous trials to average when displaying the trial
 result in the graphs.
 
`log_filename`: {animal}_%m-%d-%Y_%I-%M-%S_%p.csv
 The pattern that will be used to generate the log filenames for each
 trial. It is generated as follows::
 
     strftime(log_name_pat.format(**{'animal': animal_id, 'trial': trial,
     'block': block}))
 
 Which basically means that all instances of ``{animal}``, ``{trial}``, and
 ``{block}`` in the filename will be replaced by the
 animal name given in the GUI, the current trial, and block numbers. Then,
 it's is passed to `strftime` that formats any time parameters to get the
 log name used for that animal.
 
 If the filename matches an existing file, the new data will be appended to
 that file.
 
`n_valve_boards`: 2
 The number of valve boards connected. Each board typically controls
 8 valves.
 
`sound_file_l`: Tone.wav
 The sound file used in training as a cue when the left side is
 rewarded.
 
`sound_file_r`: Tone.wav
 The sound file used in training as a cue when the right side is
 rewarded.
 
`use_mfc`: False
 Whether a MFC is used for mixing the odor streams (i.e. two odors
 are presented in a mixed form for each trial).
 
`use_mfc_air`: False
 When :attr:`use_mfc` is False, if this is True, a MFC will be used for
 driving air as a single odor stream. No mixing is performed.
 

:ftdi_chan:

`ftdi_desc`: 
 The description of the FTDI hardware board. This a name written to the
 hardware device.
 
 :attr:`ftdi_serial` or :attr:`ftdi_desc` are used to locate the correct
 board to open. An example is `'Alder Board'` for the Alder board.
 
`ftdi_serial`: 
 The serial number of the FTDI hardware board. Can be empty if
 :attr:`ftdi_desc` is provided.
 

:mfc_a:

`mfc_id`: 0
 The MFC assigned decimal number used to communicate with that MFC.
     
 
`port_name`: 
 The COM port name of the MFC, e.g. COM3.
     
 

:mfc_air:

`mfc_id`: 0
 The MFC assigned decimal number used to communicate with that MFC.
     
 
`port_name`: 
 The COM port name of the MFC, e.g. COM3.
     
 

:mfc_b:

`mfc_id`: 0
 The MFC assigned decimal number used to communicate with that MFC.
     
 
`port_name`: 
 The COM port name of the MFC, e.g. COM3.
     
 

:odors:

`clock_bit`: 0
 The pin on the FTDI board to which the serial device's clock bit is
 connected.
 
 Defaults to zero.
 
`clock_size`: 20
 The hardware clock width used to clock out data. Defaults to 20.
     
 
`data_bit`: 0
 The pin on the FTDI board to which the serial device's data bit is
 connected.
 
 Defaults to zero.
 
`latch_bit`: 0
 The pin on the FTDI board to which the serial device's latch bit is
 connected.
 
 Defaults to zero.
 
`num_boards`: 1
 The number of serial boards connected in series to the FTDI device.
 
 Each board is a 8-channel port. Defaults to 1.
 
`output`: True
 Whether the serial device is a output or input device. If input a
 :class:`pybarst.ftdi.switch.FTDISerializerIn` will be used, otherwise a
 :class:`pybarst.ftdi.switch.FTDISerializerOut` will be used.
 
