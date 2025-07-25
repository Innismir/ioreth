#
# Ioreth - An APRS library and bot
# Copyright (C) 2020  Alexandre Erwin Ittner, PP5ITT <alexandre@ittner.com.br>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
#

import sys
import time
import logging
import configparser
import os
import re
import random
import sqlite3

logging.basicConfig()
logger = logging.getLogger(__name__)

from cronex import CronExpression

from .clients import AprsClient
from . import aprs
from . import remotecmd
from . import utils



class BotAprsHandler(aprs.Handler):
    def __init__(self, callsign, client):
        aprs.Handler.__init__(self, callsign)
        self._client = client
        self.conn = sqlite3.connect("/opt/ioreth/ioreth.db")


    def on_aprs_message(self, source, addressee, text, origframe, msgid=None, via=None):
        """Handle an APRS message.

        This may be a directed message, a bulletin, announce ... with or
        without confirmation request, or maybe just trash. We will need to
        look inside to know.
        """

        if addressee.strip().upper() != self.callsign.upper():
            # This message was not sent for us.
            return

        if re.match(r"^(ack|rej)\d+", text):
            # We don't ask for acks, but may receive them anyway. Spec says
            # acks and rejs must be exactly "ackXXXX" and "rejXXXX", case
            # sensitive, no spaces. Be a little conservative here and do
            # not try to interpret anything else as control messages.
            logger.info("Ignoring control message %s from %s", text, source)
            return

        self.handle_aprs_msg_bot_query(source, text, origframe)
        if msgid:
            # APRS Protocol Reference 1.0.1 chapter 14 (page 72) says we can
            # reject a message by sending a rejXXXXX instead of an ackXXXXX
            # "If a station is unable to accept a message". Not sure if it is
            # semantically correct to use this for an invalid query for a bot,
            # so always acks.
            logger.info("Sending ack to message %s from %s.", msgid, source)
            self.send_aprs_msg(source, "ack" + msgid)

    def handle_aprs_msg_bot_query(self, source, text, origframe):
        """We got an text message direct to us. Handle it as a bot query.
        TODO: Make this a generic thing.

        source: the sender's callsign+SSID
        text: message text.
        """

        qry_args = text.lstrip().split(" ", 1)
        qry = qry_args[0].lower()
        args = ""
        if len(qry_args) == 2:
            args = qry_args[1]

        curdate = time.strftime("%Y%m%d%H%M%S")
        cur = self.conn.cursor()
        dupe_check = cur.execute ("SELECT * FROM debouncer WHERE callsign = ? AND message = ? AND datetime > ?", (source,qry,(int(curdate)-30)))
        if dupe_check.fetchone() is None:
            cur.execute("INSERT INTO debouncer(callsign, message, datetime) VALUES (?, ?, ?)", (source,qry,curdate))
            self.conn.commit()
        else:
            logger.info("Ignoring Dupe Message from %s", source)
            return

        random_replies = {
            "mellon": "*door opens*",
            "mellon!": "**door opens**  🚶🚶🚶🚶🚶🚶🚶🚶🚶  💍→🌋",
            "meow": "=^.^=  purr purr  =^.^=",
            "clacks": "GNU Terry Pratchett",
            "73": "73 🖖",
        }

        if qry == "ping":
            self.send_aprs_msg(source, "Pong! " + args)
        elif qry == "?aprst" or qry == "?ping?":
            tmp_lst = (
                origframe.to_aprs_string()
                .decode("utf-8", errors="replace")
                .split("::", 2)
            )
            self.send_aprs_msg(source, tmp_lst[0] + ":")
        elif qry == "netcheckin" or qry == "cq":
            net = args.lstrip().split(" ", 1)[0]
            if self.aprs_net_checkin(source, net):
                self.send_aprs_msg(source, "OK, Net Check in for " + net + " Successful!")
            else:
                self.send_aprs_msg(source, "OK, Net Check in for " + net + " Failed. Uh oh") 
        elif qry == "netcheckout":
            net = args.lstrip().split(" ", 1)[0]
            if self.aprs_net_checkout(source, net):
                self.send_aprs_msg(source, "OK, Net Check out for " + net + " Successful! 73!")
            else:
                self.send_aprs_msg(source, "OK, Net Check out for " + net + " Failed. Uh oh") 
        elif qry == "netusers":
            net = args.lstrip().split(" ", 1)[0]
            try:
                flags = args.lstrip().split(" ", 1)[1]
            except IndexError:
                flags = None  # flags

            if flags == "all":
                self.aprs_net_userlist(source, net, True)
            else:
                self.aprs_net_userlist(source, net, False)
        elif qry == "netmsg":
            net = args.lstrip().split(" ", 1)[0]
            try:
                message = args.lstrip().split(" ", 1)[1]
            except IndexError:
               self.send_aprs_msg(source, "Pretty cowardly not giving me a message to send!")
               return
            self.aprs_net_blastmessage(source, net, message)

        elif qry == "version":
            self.send_aprs_msg(source, "Python " + sys.version.replace("\n", " "))
        elif qry == "time":
            self.send_aprs_msg(
                source, "Localtime is " + time.strftime("%Y-%m-%d %H:%M:%S UTC%Z")
            )
        elif qry == "help":
            self.send_aprs_msg(source, "Valid commands: ping, version, time, help")
        elif qry in random_replies:
            self.send_aprs_msg(source, random_replies[qry])
        else:
            self.send_aprs_msg(source, "I'm a bot. Send 'help' for command list")

    def aprs_net_checkin(self, from_call, net):
        logger.info("Checking in %s to APRS Net %s.", from_call, net)
        try: 
            curdate = time.strftime("%Y%m%d")
            cur = self.conn.cursor()
            cur.execute("INSERT INTO netcontrol(callsign, net_name, date) VALUES(?, ?, ?)", (from_call, net, curdate))
            self.conn.commit()
            return True 
        except Exception:
            return False

    def aprs_net_checkout(self, from_call, net):
        logger.info("Checking out %s from APRS Net %s.", from_call, net)
        try: 
            conn = sqlite3.connect("/opt/ioreth/ioreth.db")
            curdate = time.strftime("%Y%m%d")
            cur = self.conn.cursor()
            cur.execute("DELETE FROM netcontrol WHERE callsign = ? AND net_name = ?", (from_call, net))
            self.conn.commit()
            return True 
        except Exception:
            return False
        return True 

    def aprs_net_userlist(self, from_call, net, all):
        logger.info("Sending APRS Net user list to %s for APRS Net %s.", from_call, net)
        try:
            curdate = time.strftime("%Y%m%d")
            cur = self.conn.cursor()
            if (all):
                cur.execute("SELECT callsign FROM netcontrol WHERE callsign = ? AND net_name = ? AND date = ?", (from_call, net, curdate))
            else:
                cur.execute("SELECT callsign FROM netcontrol WHERE callsign = ? AND net_name = ? AND date = ? LIMIT 5", (from_call, net, curdate))
            rows = cur.fetchall()
            message = 'Current Calls for ' + net + ': '
            for row in rows:
                if len(row[0]) > 50:
                    self.send_aprs_msg(from_call, message)
                    message = ''
                message = message + ' ' + row[0]
            self.send_aprs_msg(from_call, message)
            self.conn.commit()
            return True 
        except Exception:
            return False

    def aprs_net_blastmessage(self, from_call, net, message):
        logger.info("Sending APRS Net message to %s from %s.", net, from_call)
        try:
            curdate = time.strftime("%Y%m%d")
            cur = self.conn.cursor()
            cur.execute("SELECT callsign FROM netcontrol WHERE callsign = ? AND net_name = ? AND date = ?", (from_call, net, curdate))
            rows = cur.fetchall()
            for row in rows:
                self.send_aprs_msg(from_call, from_call + "> " + message)
                time.sleep(1)
            self.conn.commit()
            return True
        except Exception:
            return False


    def send_aprs_msg(self, to_call, text):
        logger.info("Sending '%s' to %s", to_call, text)
        self._client.enqueue_frame(self.make_aprs_msg(to_call, text))

    def send_aprs_status(self, status):
        self._client.enqueue_frame(self.make_aprs_status(status))


class SystemStatusCommand(remotecmd.BaseRemoteCommand):
    def __init__(self, cfg):
        remotecmd.BaseRemoteCommand.__init__(self, "system-status")
        self._cfg = cfg
        self.status_str = ""

    def run(self):
        net_status = (
            self._check_host_scope("Eth", "eth_host")
            + self._check_host_scope("Inet", "inet_host")
            + self._check_host_scope("DNS", "dns_host")
            + self._check_host_scope("VPN", "vpn_host")
        )
        self.status_str = "At %s: Uptime %s" % (
            time.strftime("%Y-%m-%d %H:%M:%S UTC%Z"),
            utils.human_time_interval(utils.get_uptime()),
        )
        if len(net_status) > 0:
            self.status_str += "," + net_status

    def _check_host_scope(self, label, cfg_key):
        if not cfg_key in self._cfg:
            return ""
        ret = utils.simple_ping(self._cfg[cfg_key])
        return " " + label + (":Ok" if ret else ":Err")


class ReplyBot(AprsClient):
    def __init__(self, config_file):
        AprsClient.__init__(self)
        self._aprs = BotAprsHandler("", self)
        self._config_file = config_file
        self._config_mtime = None
        self._cfg = configparser.ConfigParser()
        self._cfg.optionxform = str  # config is case-sensitive
        self._check_updated_config()
        self._last_blns = time.monotonic()
        self._last_cron_blns = 0
        self._last_status = time.monotonic()
        self._last_reconnect_attempt = 0
        self._rem = remotecmd.RemoteCommandHandler()

    def _load_config(self):
        try:
            self._cfg.clear()
            self._cfg.read(self._config_file)
            self.addr = self._cfg["tnc"]["addr"]
            self.port = int(self._cfg["tnc"]["port"])
            self._aprs.callsign = self._cfg["aprs"]["callsign"]
            self._aprs.path = self._cfg["aprs"]["path"]
        except Exception as exc:
            logger.error(exc)

    def _check_updated_config(self):
        try:
            mtime = os.stat(self._config_file).st_mtime
            if self._config_mtime != mtime:
                self._load_config()
                self._config_mtime = mtime
                logger.info("Configuration reloaded")
        except Exception as exc:
            logger.error(exc)

    def on_connect(self):
        logger.info("Connected")

    def on_disconnect(self):
        logger.warning("Disconnected! Will try again soon...")

    def on_recv_frame(self, frame):
        self._aprs.handle_frame(frame)

    def _update_bulletins(self):
        if not self._cfg.has_section("bulletins"):
            return

        max_age = self._cfg.getint("bulletins", "send_freq", fallback=600)

        # There are two different time bases here: simple bulletins are based
        # on intervals, so we can use monotonic timers to prevent any crazy
        # behavior if the clock is adjusted and start them at arbitrary moments
        # so we don't need to worry about transmissions being concentrated at
        # some magic moments. Rule-based blns are based on wall-clock time, so
        # we must ensure they are checked exactly once a minute, behaves
        # correctly when the clock is adjusted, and distribute the transmission
        # times to prevent packet storms at the start of minute.

        now_mono = time.monotonic()
        now_time = time.time()

        # Optimization: return ASAP if nothing to do.
        if (now_mono <= (self._last_blns + max_age)) and (
            now_time <= (self._last_cron_blns + 60)
        ):
            return

        bln_map = dict()

        # Find all standard (non rule-based) bulletins.
        keys = self._cfg.options("bulletins")
        keys.sort()
        std_blns = [
            k for k in keys if k.startswith("BLN") and len(k) > 3 and "_" not in k
        ]

        # Do not run if time was not set yet (e.g. Raspberry Pis getting their
        # time from NTP but before conecting to the network)
        time_was_set = time.gmtime().tm_year > 2000

        # Map all matching rule-based bulletins.
        if time_was_set and now_time > (self._last_cron_blns + 60):
            # Randomize the delay until next check to prevent packet storms
            # in the first seconds following a minute. It will, of course,
            # still run within the minute.
            self._last_cron_blns = 60 * int(now_time / 60.0) + random.randint(0, 30)

            cur_time = time.localtime()
            utc_offset = cur_time.tm_gmtoff / 3600  # UTC offset in hours
            ref_time = cur_time[:5]  # (Y, M, D, hour, min)

            for k in keys:
                # if key is "BLNx_rule_x", etc.
                lst = k.split("_", 3)
                if (
                    len(lst) == 3
                    and lst[0].startswith("BLN")
                    and lst[1] == "rule"
                    and (lst[0] not in std_blns)
                ):
                    expr = CronExpression(self._cfg.get("bulletins", k))
                    if expr.check_trigger(ref_time, utc_offset):
                        bln_map[lst[0]] = expr.comment

        # If we need to send standard bulletins now, copy them to the map.
        if now_mono > (self._last_blns + max_age):
            self._last_blns = now_mono
            for k in std_blns:
                bln_map[k] = self._cfg.get("bulletins", k)

        if len(bln_map) > 0:
            to_send = [(k, v) for k, v in bln_map.items()]
            to_send.sort()
            for (bln, text) in to_send:
                logger.info("Posting bulletin: %s=%s", bln, text)
                self._aprs.send_aprs_msg(bln, text)

    def _update_status(self):
        if not self._cfg.has_section("status"):
            return

        max_age = self._cfg.getint("status", "send_freq", fallback=600)
        now_mono = time.monotonic()
        if now_mono < (self._last_status + max_age):
            return

        self._last_status = now_mono
        self._rem.post_cmd(SystemStatusCommand(self._cfg["status"]))

    def _check_reconnection(self):
        if self.is_connected():
            return
        try:
            # Server is in localhost, no need for a fancy exponential backoff.
            if time.monotonic() > self._last_reconnect_attempt + 5:
                logger.info("Trying to reconnect")
                self._last_reconnect_attempt = time.monotonic()
                self.connect()
        except ConnectionRefusedError as e:
            logger.warning(e)

    def on_loop_hook(self):
        AprsClient.on_loop_hook(self)
        self._check_updated_config()
        self._check_reconnection()
        self._update_bulletins()
        self._update_status()

        # Poll results from external commands, if any.
        while True:
            rcmd = self._rem.poll_ret()
            if not rcmd:
                break
            self.on_remote_command_result(rcmd)

    def on_remote_command_result(self, cmd):
        logger.debug("ret = %s", cmd)

        if isinstance(cmd, SystemStatusCommand):
            self._aprs.send_aprs_status(cmd.status_str)
