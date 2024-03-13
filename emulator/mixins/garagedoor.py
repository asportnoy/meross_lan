""""""

import asyncio
import typing

from custom_components.meross_lan.merossclient import (
    const as mc,
    get_element_by_key,
    update_dict_strict,
    update_dict_strict_by_key,
)

if typing.TYPE_CHECKING:
    from .. import MerossEmulator


class GarageDoorMixin(MerossEmulator if typing.TYPE_CHECKING else object):

    OPENDURATION = 10
    CLOSEDURATION = 10

    def _SET_Appliance_GarageDoor_Config(self, header, payload):
        p_config = self.descriptor.namespaces[mc.NS_APPLIANCE_GARAGEDOOR_CONFIG][
            mc.KEY_CONFIG
        ]
        update_dict_strict(p_config, payload[mc.KEY_CONFIG])
        return mc.METHOD_SETACK, {}

    def _SET_Appliance_GarageDoor_MultipleConfig(self, header, payload):
        p_config = self.descriptor.namespaces[
            mc.NS_APPLIANCE_GARAGEDOOR_MULTIPLECONFIG
        ][mc.KEY_CONFIG]
        for p_payload_channel in payload[mc.KEY_CONFIG]:
            """{"channel":3,"doorEnable":0,"timestamp":1699130748,"timestampMs":663,"signalClose":10000,"signalOpen":10000,"buzzerEnable":1}"""
            p_config_channel = update_dict_strict_by_key(p_config, p_payload_channel)
            p_config_channel[mc.KEY_TIMESTAMP] = self.epoch
        return mc.METHOD_SETACK, {}

    def _GET_Appliance_GarageDoor_State(self, header, payload):
        # return everything...at the moment we always query all
        p_garageDoor: list = self.descriptor.digest[mc.KEY_GARAGEDOOR]
        if len(p_garageDoor) == 1:
            # un-pack the list since real traces show no list
            # in this response payloads (we only have msg100 so far..)
            return mc.METHOD_GETACK, {mc.KEY_STATE: p_garageDoor[0]}
        else:
            return mc.METHOD_GETACK, {mc.KEY_STATE: p_garageDoor}

    def _SET_Appliance_GarageDoor_State(self, header, payload):
        p_request = payload[mc.KEY_STATE]
        request_channel = p_request[mc.KEY_CHANNEL]
        request_open = p_request[mc.KEY_OPEN]

        p_state = get_element_by_key(
            self.descriptor.digest[mc.KEY_GARAGEDOOR], mc.KEY_CHANNEL, request_channel
        )

        p_response = dict(p_state)
        if request_open != p_state[mc.KEY_OPEN]:

            def _state_update_callback():
                p_state[mc.KEY_OPEN] = request_open

            asyncio.get_event_loop().call_later(
                self.OPENDURATION if request_open else self.CLOSEDURATION,
                _state_update_callback,
            )

        p_response[mc.KEY_EXECUTE] = 1
        return mc.METHOD_SETACK, {mc.KEY_STATE: p_response}
