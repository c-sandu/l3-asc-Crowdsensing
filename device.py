"""
This module represents a device.

Computer Systems Architecture Course
Assignment 1
March 2017
"""

from threading import Event, Thread, Lock, Semaphore
from Queue import Queue

from barrier import ReusableBarrierCond


class Device(object):
    """
    Class that represents a device.
    """

    def __init__(self, device_id, sensor_data, supervisor):
        """
        Constructor.

        @type device_id: Integer
        @param device_id: the unique id of this node; between 0 and N-1

        @type sensor_data: List of (Integer, Float)
        @param sensor_data: a list containing (location, data) as measured by
                            this device

        @type supervisor: Supervisor
        @param supervisor: the testing infrastructure's control and validation
                           component
        """
        self.device_id = device_id
        self.sensor_data = sensor_data
        self.supervisor = supervisor

        self.scripts = [] # all scripts received by a device from the beginning
        self.work_queue = Queue() # scripts to run int the current timepoint
        self.neighbours = [] # neighbours for the current timepoint

        self.timepoint_done = Event() # no more scripts incoming
        self.setup_ready = Event() # used by Device0 to share variables
        self.neighbours_set = Event() # workers wait for neighbours to be set
        self.scripts_mutex = Semaphore(1) # using a Lock generated a pylint err
        self.location_locks_mutex = None # just to be sure
        self.location_locks = {} # one lock per location
        self.timepoint_barrier = None # devices end timepoint at the same time

        self.thread = DeviceThread(self)
        # 8 workers for script execution
        self.workers = [DeviceWorker(self) for _ in range(8)]

    def __str__(self):
        """
        Pretty prints this device.

        @rtype: String
        @return: a string containing the id of this device
        """
        return "Device %d" % self.device_id

    def setup_devices(self, devices):
        """
        Setup the devices before simulation begins.

        @type devices: List of Device
        @param devices: list containing all devices
        """

        # Only Device 0 will initialize the barrier and location_locks_mutex
        if self.device_id == 0:
            self.timepoint_barrier = ReusableBarrierCond(len(devices))
            self.location_locks_mutex = Lock()
            self.setup_ready.set() # signals other devices
        else:
            # find Device0 in list of devices
            device = next(device for device in devices if device.device_id == 0)
            device.setup_ready.wait() # wait for Device0 signal
            self.timepoint_barrier = device.timepoint_barrier
            self.location_locks = device.location_locks
            self.location_locks_mutex = device.location_locks_mutex

        # Initialize location locks for each possible location
        with self.location_locks_mutex:
            for location in self.sensor_data.keys():
                if location not in self.location_locks:
                    self.location_locks[location] = Lock()

        # Start device thread and workers
        self.thread.start()
        for worker in self.workers:
            worker.start()


    def assign_script(self, script, location):
        """
        Provide a script for the device to execute.
        Invoked by the tester.

        @type script: Script
        @param script: the script to execute from now on at each timepoint;
                       None if the current timepoint has ended

        @type location: Integer
        @param location: the location for which the script is interested in
        """
        # blocks until the neighbours for current timepoint are set
        self.neighbours_set.wait()

        if script is not None:
            with self.scripts_mutex:
                self.scripts.append((script, location))
            self.work_queue.put((script, location))
        else:
            self.neighbours_set.clear() # resets lock for the next timepoint
            self.timepoint_done.set() # notifies device thread

    def get_data(self, location):
        """
        Returns the pollution value this device has for the given location.
        Thread safety is enforced by the location lock.

        @type location: Integer
        @param location: a location for which obtain the data

        @rtype: Float
        @return: the pollution value
        """
        if location in self.sensor_data:
            return self.sensor_data[location]
        return None

    def set_data(self, location, data):
        """
        Sets the pollution value stored by this device for the given location.
        Thread safety is enforced by the location lock

        @type location: Integer
        @param location: a location for which to set the data

        @type data: Float
        @param data: the pollution value
        """
        if location in self.sensor_data:
            self.sensor_data[location] = data

    def shutdown(self):
        """
        Instructs the device to shutdown (terminate all threads). This method
        is invoked by the tester. This method must block until all the threads
        started by this device terminate.
        """
        self.thread.join()
        for worker in self.workers:
            self.work_queue.put((None, None))

        for worker in self.workers:
            worker.join()



class DeviceThread(Thread):
    """
    Class that implements the device's worker thread.
    """

    def __init__(self, device):
        """
        Constructor.

        @type device: Device
        @param device: the device which owns this thread
        """
        Thread.__init__(self, name="Device Thread %d" % device.device_id)
        self.device = device

    def run(self):

        while True:
            # get the current neighbourhood
            self.device.neighbours = self.device.supervisor.get_neighbours()

            # test for terminating condition
            if self.device.neighbours is None:
                break

            for (script, location) in self.device.scripts:
                self.device.work_queue.put((script, location))

            # signals assign_script that we are ready to accept scripts in the
            # current timepoint
            self.device.neighbours_set.set()

            # wait until all scripts for the current timepoint were received
            self.device.timepoint_done.wait()

            # wait until the work_queue is empty
            self.device.work_queue.join()

            # reset timepoint_done for the next timepoint
            self.device.timepoint_done.clear()

            # wait for all devices
            self.device.timepoint_barrier.wait()



class DeviceWorker(Thread):
    """
    Worker class for running scripts on a device. Blocks on the work_queue.get()
    call, and terminates when (None, None) is obtained from the queue.
    """

    def __init__(self, device):
        """
        Constructor.

        @type device: Device
        @param device: the device which owns this thread
        """
        Thread.__init__(self, name="Device %d Worker" % device.device_id)
        self.device = device


    def run(self):

        while True:
            # naturally, this will happen only after the neighbours are set
            (script, location) = self.device.work_queue.get(block=True)

            # test for terminating condition
            if script is None and location is None:
                # make sure to notify the queue that work is done
                self.device.work_queue.task_done()
                break

            # enforce mutual exclusion for the location referred by the script
            # set_data and get_data are thread safe, because only one thread
            # has access to the specific location
            with self.device.location_locks[location]:
                script_data = []

                for device in self.device.neighbours:
                    data = device.get_data(location)
                    if data is not None:
                        script_data.append(data)

                data = self.device.get_data(location)
                if data is not None:
                    script_data.append(data)

                if script_data != []:
                    result = script.run(script_data)

                    for device in self.device.neighbours:
                        device.set_data(location, result)

                    self.device.set_data(location, result)

            self.device.work_queue.task_done()
