import multiprocessing
import zmq
import logging
import json
import re
import chevron
import importlib

context = zmq.Context()
logger = logging.getLogger("main.interpretation")


class Blackboard(multiprocessing.Process):
    def __init__(self, config, zmq_conf):
        super().__init__()

        # <variable>: single | retain | static
        # single | retain | static : [<variable>]
        # <variable>:<pattern>
        # <variable>:<current value>
        self.variable_fmap, self.variable_rmap, self.patterns, self._blackboard = process_variable_config(
            config['variable'])
        self.variable_rmap['single'].append("timestamp")  # always a single use

        self.process_package = config['processing'].get('directory', None)
        self.process_for_variable = reverse_map_processing(config['processing']['process'])
        self.processes = config['processing']['process']  # <variable>: [<functions>]
        # Todo: run hooks after initial blackboard setup

        self.triggered_by_variable = reverse_map_triggers(config['output'])  # <variable>:[output_name]
        self.outputs = {item['name']: item for item in config['output']}  # <output_name>:<output>
        self.trigger_tracking = {item['name']: set() for item in config['output']}

        self.singles_to_clear = set()

        self.zmq_conf = zmq_conf
        self.zmq_in = None
        self.zmq_out = None

    def do_connect(self):
        self.zmq_in = context.socket(self.zmq_conf['in']['type'])
        if self.zmq_conf['in']["bind"]:
            self.zmq_in.bind(self.zmq_conf['in']["address"])
        else:
            self.zmq_in.connect(self.zmq_conf['in']["address"])

        self.zmq_out = context.socket(self.zmq_conf['out']['type'])
        if self.zmq_conf['out']["bind"]:
            self.zmq_out.bind(self.zmq_conf['out']["address"])
        else:
            self.zmq_out.connect(self.zmq_conf['out']["address"])

    def run(self):
        self.do_connect()
        logger.info("connected")
        while True:
            # get barcode
            msg = self.get_input_message()
            try:
                barcode = msg['barcode']
                timestamp = msg['timestamp']
                self._blackboard['timestamp'] = timestamp
            except KeyError:
                logger.warning(f"Message did not not have required keys: {msg}")
                continue
            # extract variable
            variable, value = self.extract_variable(barcode)
            # apply to Blackboard
            self._blackboard[variable] = value
            # process hooks
            self.process_hooks(variable, value)
            # evaluate triggers
            triggered_set = self.get_triggered(variable)
            # form outputs
            outputs = self.get_outputs(triggered_set)
            # clear single use
            self.clear_singles()
            # dispatch outputs
            self.dispatch(outputs)

    def get_input_message(self):
        while self.zmq_in.poll(1000, zmq.POLLIN) == 0:  # blocks until a message arrives
            pass
        try:
            msg = self.zmq_in.recv(zmq.NOBLOCK)
            logger.debug(f"got {msg}")
            return json.loads(msg)
        except zmq.ZMQError:
            pass
        return {}

    def extract_variable(self, barcode):
        found_variable = None
        value = None
        for variable, pattern in self.patterns.items():
            match = re.search(pattern, barcode)
            if match:
                found_variable = variable
                value = match.group(1)
                break
        logger.debug(f"Extracted {found_variable}={value}")
        return found_variable, value

    def process_hooks(self, var_name, var_value):
        if var_name not in self.process_for_variable:
            return {}

        process_name = self.process_for_variable[var_name]
        process_details = self.processes[process_name]
        extra_args = process_details.get('extra_args', [])
        package_name = self.process_package
        module_name = process_details.get('module', None)
        process_outputs = process_details.get('output_as', [])

        if module_name is None or package_name is None:
            logger.error(f"Insufficient config for process {process_name} "
                         f"package={package_name} module={module_name}")
            return {}

        try:
            hook_module = importlib.import_module(f"{package_name}.{module_name} for variable {var_name}")
            logger.debug(f"Imported {hook_module}")
        except ModuleNotFoundError as e:
            logger.error(f"Trying to find module {package_name}.{module_name} "
                         f"for variable {var_name} lead to exception: {e}")
            return {}

        try:
            result = hook_module.function(var_name, var_value, extra_args)
            if result:
                logger.info(
                    f"Processing for {var_name} in module {package_name}.{module_name} resulted in {result}")
            else:
                logger.debug(f"Processing for {var_name} in module {package_name}.{module_name} did return")
                result = []
        except Exception as e:
            result = []
            logger.error(f"Processing for {var_name} in module {package_name}.{module_name} lead to exception{e}")

        lo = len(process_outputs)
        lr = len(result)
        compress_expand_result = result[0:lo]
        compress_expand_result.extend([None] * (lo - lr))
        out = dict(zip(process_outputs, compress_expand_result))
        return out

    def get_triggered(self, variable):
        base_set = self.triggered_by_variable.get(variable, [])
        triggered_set = []
        for name in base_set:
            trigger_policy = self.outputs[name].get('trigger_policy', "any")
            trigger_set = set(self.outputs[name]['triggers'])
            if trigger_policy == "all":
                self.trigger_tracking[name].add(variable)
                if self.trigger_tracking[name] == trigger_set:
                    triggered_set.append(name)
                    self.trigger_tracking[name].clear()
            else:
                triggered_set.append(name)

        logger.debug(f"Triggered set = {triggered_set}")
        return triggered_set

    def get_outputs(self, triggered_set):
        outputs = []
        for triggered_output in triggered_set:
            outputs.append(self.form_output(triggered_output))
        logger.debug(f"Outputs are {outputs}")
        return outputs

    def form_output(self, name):
        config = self.outputs[name]
        topic = chevron.render(config['topic'], self._blackboard)
        payload = {}
        for key, variable in config['payload'].items():
            payload[key] = self._blackboard.get(variable)
            if variable in self.variable_rmap['single']:
                self.singles_to_clear.add(variable)
        return {'topic': topic, 'payload': payload}

    def clear_singles(self):
        for var in self.singles_to_clear:
            self._blackboard[var] = None

    def dispatch(self, outputs):
        for output_msg in outputs:
            logger.debug(f"Dispatching {output_msg}")
            # send
            self.zmq_out.send_json(output_msg)


def process_variable_config(variables):
    fmap = {}
    rmap = {'single': [], 'retain': [], 'static': []}
    patterns = {}
    initial_blackboard = {}

    for var in variables:
        name = var.get('name')
        var_type = var.get('type')

        if name is None:
            logger.warning(f"Incomplete variable in config: {var}")
            continue

        if var_type not in ['static', 'single', 'retain']:
            logger.warning(f"Invalid type {var_type} for variable {name}")
            continue

        fmap[name] = var_type
        rmap[var_type].append(name)

        pattern = var.get('pattern')
        if pattern is not None:
            patterns[name] = pattern

        if var_type == 'single':
            initial_blackboard[name] = None
        if var_type == 'static':
            initial_blackboard[name] = var.get("value")
        if var_type == 'retain':
            initial_blackboard[name] = var.get("initial")

    return fmap, rmap, patterns, initial_blackboard


def reverse_map_processing(processes):
    rmap = {}
    for process_name, process_details in processes.items():
        variable = process_details.get('apply_to', None)
        if variable:
            rmap[variable] = process_name
    return rmap


def reverse_map_triggers(outputs):
    rmap = {}
    for output in outputs:
        name = output.get('name')

        if name is None:
            logger.warning(f"Output does not have name: {output}")
            continue

        triggers = output.get('triggers', [])
        for trigger in triggers:
            if trigger in rmap:
                rmap[trigger].append(name)
            else:
                rmap[trigger] = [name]

    return rmap
