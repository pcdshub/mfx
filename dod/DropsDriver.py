import logging
import pprint
import argparse

from http.client import HTTPConnection
from multiprocessing import Queue, Semaphore
from dod.ServerResponse import ServerResponse
from dod.SupporEndsHandler import SupportedEndsHandler
from dod.HTTPTransceiver import HTTPTransceiver

logger = logging.getLogger(__name__)


def parse_arguments(obj):
  # arg parse and validation
  parser = argparse.ArgumentParser(
                    prog='DoDMiddleware',
                    description='allows users to interact with droplet on demand http api')

  group = parser.add_mutually_exclusive_group(required=True)  # only accept one of the following
  # get, trivial
  group.add_argument("-g", "--get", help="Call HTTP get on endpoint", type=str, choices=obj.supported_ends()['get'])
  group.add_argument("-c", "--connect", help="Connect to the API", action='store_true')  # TODO: take string argument of username
  group.add_argument("-d", "--disconnect", help="Call HTTP get on endpoint", action='store_true') 
  # do
  group.add_argument("-m", "--move", help="move to enumerated position", type=str, choices=obj.supported_ends()['do']["/DoD/do/Move?PositionName={value}"])
  group.add_argument("-t", "--task", help='execute enumerated task', type=str, choices=obj.supported_ends()['do']["/DoD/do/ExecuteTask?TaskName={value}"])

  return parser.parse_args()

'''
Simple HTTP Client wrapper.
Takes ip and port on construction can send data on socket and print reply
Can be invoked via command line args or as orchestrated by higher level software
'''


class myClient:
  def __init__(self, ip, port, supported_json="supported.json", reload=True, queue=None, **kwargs):
    # dto pipelines
    self.__queue__ = Queue()
    self.__queue_ready__ = Semaphore(value=0)
    # configure connection object
    self.__IP__ = ip
    self.__PORT__ = port
    self.conn = HTTPConnection(host=self.__IP__, port=self.__PORT__)
    self.transceiver = HTTPTransceiver(self.conn, self.__queue__, self.__queue_ready__)
    logger.info(f"Connected to ip: {ip} port: {port}")

    # configuration persitence, updating
    self.supported_ends_handler = SupportedEndsHandler(supported_json,self.conn)
    if (reload):
      self.supported_ends_handler.reload_all()

    # convinient member lambda for grabbing supported endpoitns
    self.supported_ends = lambda : self.supported_ends_handler.get_endpoints()
    pprint.pprint(self.supported_ends())

  def __del__(self):
      # close network connection
      self.conn.close()

  '''
  Middleware interaction defintions
  Here we define specific interactions that the machine is capable of fielding
  These actions are exposed as member functions of this driver class. 
  '''

  def middle_invocation_wrapper(func):
    '''
    Define a decorator function to adorn all of these 'high' middleware calls
    Logs what functions is being called and returns the response. 
    '''
    def inner(self, *args):
      logger.info(f"Invoking {func.__name__}")
      func(self, *args)
      resp = self.get_response()
      # TODO: Do something with None response globally
      # Check if we have a GUI (get_status) that needs to be cleared, May need
      # to happen per function basis
      return resp
    return inner

  @middle_invocation_wrapper
  def connect(self, user : str):
      """
        Required to send 'Do' requests
      """
      self.send(f"/DoD/Connect?ClientName={user}")

  @middle_invocation_wrapper
  def disconnect(self):
      """
        The client can end the connection with access to ‘Do’ requests.
        Clicking the button ‘Disable API Control’ on the UI has the same effect.
      """
      self.send("/DoD/Disconnect")

  @middle_invocation_wrapper
  def get_status(self):
      """
        Returns Robot Status
      """
      self.send("/DoD/get/Status")


  @middle_invocation_wrapper
  def move(self, position : str):
      """
        Moves the drive to a position taken from the list of 'PositionNames'
      """
      self.send(f"/DoD/do/Move?PositionName={position}")

  @middle_invocation_wrapper
  def get_position_names(self):
      """
        Returns the list of positions in DOD robot
      """
      self.send(f"/DoD/get/PositionNames")

  @middle_invocation_wrapper
  def get_task_names(self):
      """
        Returns the list of tasks that are stored in the Robot by name
      """
      self.send(f"/DoD/get/TaskNames")

  @middle_invocation_wrapper
  def get_current_positions(self):
      """
        Returns the name and properties of the last selected position,
        together with the real current position coordinates.
        (The drives can have been stepped away from the stored position or 
        they include small dispenser related offsets.)
      """
      self.send(f"/DoD/get/CurrentPosition")

  @middle_invocation_wrapper
  def execute_task(self, value : str):
      """
        Runs a task from the list of ‘TaskName’.
        This operation is safe in general.
        It simulates the analog action on the UI.
      """
      self.send(f"/DoD/do/ExecuteTask?TaskName={value}")

  @middle_invocation_wrapper
  def auto_drop(self):
      """
        Runs the particular task that is linked to the UI button.
        Its name is ‘AutoDropDetection’. In principalm this endpoint is not needed.
        ‘ExecuteTask’ can be used instead.
      """
      self.send(f"/DoD/do/AutoDrop")

  @middle_invocation_wrapper
  def move_to_interaction_point(self):
      """
        The moving to the predefined position of the interaction point corresponds
        to the use of the endpoint ‘Move’. But only with this endpoint the UI
        elemts for the dispensers’ position adjustment become visible on the UI.
        The request simulates the button (beam simbol) on the UI.
      """
      self.send(f"/DoD/do/InteractionPoint")

  @middle_invocation_wrapper
  def move_x(self, value : float):
      """
        The X drive can be sent to any coordinate (the value’s unit is µm)
        within the allowed range.

        NOTE: This does not include a Z move up to the safe height nor any
        other safety feature checking whether the move from the current position
        to the selected coordinate can lead to collision or breaking of a
        dispenser Tip.
      """
      self.send(f"/DoD/do/MoveX?X={value}")

    ## API V2
  @middle_invocation_wrapper
  def get_pulse_names(self):
      """
        Returns the list of available pulse shapes for the sciPULSE channels.
      """
      self.send(f"/DoD/get/PulseNames")

  @middle_invocation_wrapper
  def get_nozzle_status(self):
      """
        Returns the activated and selected nozzles an the parameters for all
        activated nozzles. The parameter ‘Trigger’ (true/false) is not linked
        to a nozzle.

        Note: Nozzle parameters
        ‘ID’ (number),
        ‘Volt’,
        ‘Pulse’ (name or number),
        ‘Freq’ ,
        ‘Volume’ appear as an array of strings (JSON).
      """
      self.send("/DoD/get/NozzleStatus")

  @middle_invocation_wrapper
  def select_nozzle(self, channel: str):
      """
        Set the selected nozzle for dispensing and task execution etc.
        Returns a reject if the channel value is not one of the
        ‘Activated Nozzles’ (see ‘NozzleStatus’).
      """
      self.send(f"/DoD/do/SelectNozzle?Channel={channel}")


  @middle_invocation_wrapper
  def dispensing(self, state: str):
      """
        Switches between the dispensing states
        ‘Trigger’ (includes ‘Stat Continuous Dispensing’),
        ‘Free’ (‘Continuous Dispensing’ without trigger) and
        ‘Off’. Returns a reject if the value is not one of the three strings.

        (Some tasks can set the state to ‘Off’ without restarting dispensing afterwards.)
      """
      self.send(f"/DoD/do/Dispensing?State={state}")


  @middle_invocation_wrapper
  def setLED(self, duration: int, delay : int):
      """
      Sets the two strobe LED parameters ‘Delay’ (0 to 6500) and Duration (1 to 65000).
      Returns a reject if one of the values is out of range.
      """
      self.send(f"/DoD/do/SetLED?Duration={duration}&Delay={delay}")

  @middle_invocation_wrapper
  def move_y(self, value : float):
      """
          Same as for Y
      """
      #TODO: handle Dialog, Caputure None, Check if dialog and clear
      self.send(f"/DoD/do/MoveY?Y={value}")

  @middle_invocation_wrapper
  def move_z(self, value : float):
      """
          Same as for Z
      """
      self.send(f"/DoD/do/MoveZ?Z={value}")

  @middle_invocation_wrapper
  def take_probe(self, channel : int, probe_well : str, volume : float):
      """
      This endpoint requires the presence of the task ‘ProbeUptake’ (attached).
      If that is not given, the return is not a reject, but nothing happens.
      The parameters are

        ‘Channel’ (number of nozzle, includes effect as ‘SelectNozzle’),
        ‘ProbeWell’ (e.g. A1), Volume (µL). Returns a reject  if ‘Channel’ is not among
        ‘Active Nozzles’, Volume is > 250 or
        ‘ProbeWell’ is not one of the allowed wells for the selected nozzle.

      """
      self.send(f"/DoD/do/TakeProbe?Channel={channel}&ProbeWell={probe_well}&Volume={volume}")

## API V3 ##

  @middle_invocation_wrapper
  def get_task_details(self, task_name):
    '''
        Returns the content of the tasks that is specified be ‘TaskName’.
    '''
    self.send(f"/DoD/get/TaskDetails?TaskName={task_name}")

  @middle_invocation_wrapper
  def get_drive_range(self):
    '''
      Returns the maximum range of each axis (X,Y,Z) in units of µm.
    '''
    self.send(f"/DoD/get/DriveRange")

  @middle_invocation_wrapper
  def set_nozzle_parameters(self,
                            active_nozzles : str,
                            selected_nozzles: str,
                            volts : int,
                            pulse : str,
                            frequency : int):
    '''
      Sets the list of activate nozzles and of the selected nozzles for
        operations that work with more than one nozzle.
      (This overwrites and is overwritten by SelectNozzle, which only sets one nozzle channel.)
      Both values are strings with commas separating the channel numbers (e.g. “1,2,3”).
      ‘Volt’ and ‘Freq’ are integers.
      ‘Pulse’ is read as a string. It is either a integer number or the pulse
        shape name for sciPULSE channels (from PulseNames).

    '''

    self.send(f"/DoD/do/SetNozzleParameters?Active={active_nozzles}&Selected={selected_nozzles}&Volt={volts}&Pulse={pulse}&Freq={frequency}")

  @middle_invocation_wrapper
  def stop_task(self):
    '''
            Stops the running task (and moves).
    '''
    self.send(f"/DoD/do/StopTask")

  @middle_invocation_wrapper
  def set_ip_offest(self):
    '''
            This endpoint uses the current coordinates for the currently selected
            nozzle (SelectNozzle) to set the IP position (Nozzle 1) or calculates
            and sets the IP offsets (Nozzles 2, …).
            (Note: The ‘Nozzle Offset’ values in the nozzle parameter table are 
            always considered.
            Changing these would require a readjustment of the IP offsets.)
            Offsets are rejected if they exceed a maximum of 2 mm.
            Thus, the selected nozzle must be moved to the IP (InteractionPoint)
            before requesting SetIPOffset.
    '''
    self.send(f"/DoD/do/InteractionPoint")

  @middle_invocation_wrapper
  def set_humidity(self, value):
    '''
        Sets the wanted relative humidity as %rH. Values are integer.
    '''
    self.send(f"/DoD/do/SetHumidity?rH={value}")

  @middle_invocation_wrapper
  def set_cooling_temp(self, temp):
    '''
            Sets the temperature of the cooling device.
            Besides the setting of a °C value (float),
                there is the option to send the string “dewpoint”,
                which enables an automatic adjustment.
    '''
    self.send(f"/DoD/do/SetCoolingTemp?Temp={temp}")

  @middle_invocation_wrapper
  def close_dialog(self, reference, selection):
    '''
            In situations of “Status” = “Dialog” the endpoint Status provides the
                dialog’s reference, message text and button labels.
            (If the response of ‘Button2’ is empty, there is only one selection 
            available, typically with the label ‘OK.).
            This endpoint allows to close the dialog by specifying the reference and t
                he selection (“1” or “2”).
            The reference is individual, incrementing integer for each occurrence
                of a dialog, it starts a “1” when the device is initialized.

            In case of more than one open dialogs “Status” reports the last one,
                which is typically the first to be closed.
            But the remote control can try to close the earlier dialog.
    '''
    self.send(f"/DoD/do/CloseDialog?Reference={reference}&Selection={selection}")

  @middle_invocation_wrapper
  def reset_error(self):
    '''
            This endpoint is needed if after closing all (error) dialogs the status 
            “Error” persists and “ErrorMessage” (header) is not “NA”.
    '''
    self.send(f"/DoD/do/ResetError")

  '''
  send transmits a formatted HTTP GET request
  it will not check the validity of request
  it will persist result in a place that can be read... TODO: actually do this
  '''
  def send(self, endpoint):
    self.transceiver.send(endpoint)
    return

  '''
  Pops most recent response from response queue
  '''
  def get_response(self):
    return self.transceiver.get_response()


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    # init connection to client
    client = myClient(ip="172.21.148.101", port=9999)
    #client = myClient(ip="127.0.0.1", port=8081)
    # check validity of user specified arg
    args = parse_arguments(client)
    # transmit command
    if (args.connect):
        client.send("/DoD/Connect?ClientName={value}")
    elif (args.disconnect):
        client.send("/DoD/Disconnect")
    else:
        client.send(args.get)
        x = client.get_response()
        print(x.RESULTS)
