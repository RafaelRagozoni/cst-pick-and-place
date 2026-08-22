"""Reference client for the simulation bridge (BRG-02).

The Java/CST side will speak this protocol; this is the same protocol in Python, used by the tests
and useful for driving the bridge by hand. Keeping a reference implementation next to the server
means the wire format has one definition and two consumers, not two definitions.

Protocol: ZeroMQ REQ/REP, one JSON object each way. Every reply carries `ok`; on failure it carries
`error` instead of a result. One request per control cycle.

    ping  -> {protocol, physics}
    info  -> {primitives, goalSteps, stepLimit, physics}
    reset {seed, episode} -> {obs, placement, goal, success, done, step}
    step  {records}       -> {obs, goal, success, done, step}
    shutdown
"""
import json

import zmq


class BridgeError(RuntimeError):
    pass


class BridgeClient:
    def __init__(self, port=5555, host='127.0.0.1', timeout_ms=20000):
        self.ctx = zmq.Context.instance()
        self.sock = self.ctx.socket(zmq.REQ)
        self.sock.setsockopt(zmq.RCVTIMEO, timeout_ms)
        self.sock.setsockopt(zmq.LINGER, 0)
        self.sock.connect('tcp://%s:%d' % (host, port))

    def call(self, **req):
        self.sock.send_string(json.dumps(req))
        try:
            rep = json.loads(self.sock.recv())
        except zmq.Again:
            raise BridgeError('bridge did not reply within the timeout')
        if not rep.get('ok'):
            raise BridgeError(rep.get('error', 'unknown bridge error'))
        return rep

    def ping(self):
        return self.call(op='ping')

    def info(self):
        return self.call(op='info')

    def reset(self, seed, episode):
        return self.call(op='reset', seed=seed, episode=episode)

    def step(self, records):
        return self.call(op='step', records=records)

    def shutdown(self):
        try:
            return self.call(op='shutdown')
        finally:
            self.close()

    def close(self):
        self.sock.close(0)
