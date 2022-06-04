#Modified from: (c) YashDK [yash-dk@github]

import asyncio, os
from aria2p import API, Client
import time
import shutil
import aria2p
from psutil import cpu_percent, virtual_memory
from bot import LOGGER, uptime
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from functools import partial
from bot.utils import human_format
from bot.utils.bot_utils import is_magnet
from bot.utils.human_format import get_readable_file_size


class AriaDownloader():
    def __init__(self, dl_link, user_message, new_file_name=None):
        super().__init__()
        self._aloop = asyncio.get_event_loop()
        self._client = None
        self._dl_link = dl_link
        self._new_file_name = new_file_name 
        self._gid = 0
        self._user_message= user_message
        self._update_info = None

    async def get_client(self):
        if self._client is not None:
            return self._client

        aria2_daemon_start_cmd = []
        aria2_daemon_start_cmd.append("aria2c")
        #aria2_daemon_start_cmd.append("--conf-path=aria2/aria2.conf")
        aria2_daemon_start_cmd.append("--conf-path=/usr/src/app/aria2/aria2.conf")

        process = await asyncio.create_subprocess_exec(
            *aria2_daemon_start_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        await process.communicate()
        
        arcli = await self._aloop.run_in_executor(
            None, 
            partial(
                Client, 
                host="http://localhost", 
                port=8100, 
                secret=""
                )
        )
        aria2 = await self._aloop.run_in_executor(None, API, arcli)
        self._client = aria2
        return aria2

    async def add_magnet(self, aria_instance, magnetic_link, path):
        download = await self._aloop.run_in_executor(None, aria_instance.add_magnet, magnetic_link, {'dir': path})
        if download.error_message:
            error = str(download.error_message).replace('<', ' ').replace('>', ' ')
            return False, "**FAILED** \n" + error + "\n", None
        return True, "", "" + download.gid + ""

    async def add_url(self, aria_instance, text_url, path):
        uris = [text_url]
        download = await self._aloop.run_in_executor(None, aria_instance.add_uris, uris, {'dir': path})
        if download.error_message:
            error = str(download.error_message).replace('<', ' ').replace('>', ' ')
            return False, "**FAILED** \n" + error + "\n", None
        else:
            return True, "", "" + download.gid + ""

    async def add_torrent(self, aria_instance, torrent_file_path):
        if torrent_file_path is None:
            return False, "**FAILED** \n\nsomething wrong when trying to add <u>TORRENT</u> file"
        if os.path.exists(torrent_file_path):
            try:
                download = await self._aloop.run_in_executor(None, partial(aria_instance.add_torrent, torrent_file_path, uris=None, options=None, position=None))
            except Exception as e:
                return False, "**FAILED** \n" + str(e) + " \nPlease do not send slow links"
            else:
                return True, "" + download.gid + ""
        else:
            return False, "**FAILED** \n" + str(e) + " \nPlease try other sources to get workable link"

    async def execute(self):
        aria_instance = await self.get_client()
        path= os.path.join(os.getcwd(), "Downloads", str(time.time()).replace(".","")) 
        if is_magnet(self._dl_link):
            sagtus, err_message, gid = await self.add_magnet(aria_instance, self._dl_link, path) 
            if not sagtus:
                return False, err_message, None
            self._gid = gid
            statusr, error_message= await self.aria_progress_update()
            if not statusr:
                return False, error_message, None
            else:
                file = await self._aloop.run_in_executor(None, aria_instance.get_download, self._gid)
                file_path = os.path.join(file.dir, file.name)
                return True, error_message, file_path
        elif self._dl_link.lower().endswith(".torrent"):
            err_message= "Not supported .torrent files"
            return False, err_message, None  
        else:
            sagtus, err_message, gid = await self.add_url(aria_instance, self._dl_link, path)
            if not sagtus:
                return False, err_message, None 
            self._gid = gid
            statusr, error_message= await self.aria_progress_update()
            if not statusr:
               return False, error_message, None
            else:
                file = await self._aloop.run_in_executor(None, aria_instance.get_download, self._gid)
                file_path = os.path.join(file.dir, file.name)
                return True, error_message, file_path

    async def aria_progress_update(self):
        aria2 = await self.get_client()
        user_msg= self._user_message
        while True:
            try:
                file = await self._aloop.run_in_executor(None, aria2.get_download, self._gid)
                if file.followed_by_ids:
                    self._gid = file.followed_by_ids[0]
                self._update_info = file
                complete = file.is_complete
                update_message1= ""
                sleeps= False
                if not complete:
                    if not file.error_message:
                        if file is None:
                            error_message= "Error in fetching the direct DL"
                            return False, error_message
                        else:
                            sleeps = True
                            update_message= await self.create_update_message()
                            if update_message1 != update_message:
                                try:
                                    data = "cancel_aria2_{}".format(self._gid)
                                    await user_msg.edit(text=update_message, reply_markup=(InlineKeyboardMarkup([
                                            [InlineKeyboardButton('Cancel', callback_data=data.encode("UTF-8"))]
                                            ])))
                                    update_message1 = update_message
                                except Exception as e:
                                    pass

                            if sleeps:
                                if complete:
                                    await user_msg.edit("Completed")     
                                    break     
                                sleeps = False
                                await asyncio.sleep(2)
                    else:
                        msg = file.error_message
                        error_message = f"The aria download failed due to this reason:- {msg}"
                        return False, error_message
                else:
                    error_message= f"Download completed: `{file.name}` - (`{file.total_length_string()}`)"
                    return True, error_message
            except aria2p.client.ClientException as e:
                if " not found" in str(e) or "'file'" in str(e):
                    error_reason = "Aria download canceled."
                    return False, error_reason
                else:
                    LOGGER.warning("Error due to a client error.")
                pass
            except RecursionError:
                file.remove(force=True)
                error_reason = "The link is basically dead."
                return False, error_reason
            except Exception as e:
                LOGGER.info(str(e))
                self._is_errored = True
                if " not found" in str(e) or "'file'" in str(e):
                    error_reason = "Aria download canceled."
                    return False, error_reason
                else:
                    LOGGER.warning(str(e))
                    error_reason =  f"Error: {str(e)}"
                    return False, error_reason

    async def create_update_message(self):
        file= self._update_info
        downloading_dir_name = "N/A"
        try:
            downloading_dir_name = str(file.name)
        except:
            pass
        bottom_status= ''
        diff = time.time() - uptime
        diff = human_format.human_readable_timedelta(diff)
        usage = shutil.disk_usage("/")
        free = human_format.human_readable_bytes(usage.free) 
        bottom_status += f"\n\n<b>CPU:</b> {cpu_percent()}% | <b>FREE:</b> {free}" + f"\n<b>RAM:</b> {virtual_memory().percent}% | <b>UPTIME:</b> {diff}"
        msg = "<b>Name:</b>{}\n".format(downloading_dir_name)
        msg += "<b>Status:</b> Downloading...\n"
        msg += "{}\n".format(self.get_progress_bar_string())
        msg += "<b>P:</b> {}%\n".format(round(file.progress, 2))
        msg += "<b>Downloaded:</b> {} <b>of:</b> {}\n".format(get_readable_file_size(file.completed_length), file.total_length_string())
        msg += "<b>Speed:</b> {}".format(file.download_speed_string()) + "|" + "<b>ETA: {} Mins\n</b>".format(file.eta_string())
        try:
            msg += f"<b>Seeders:</b> {file.num_seeders}" 
            msg += f" | <b>Peers:</b> {file.connections}"
        except:
            pass
        try:
            msg += f"<b>Seeders:</b> {file.num_seeds}"
            msg += f" | <b>Leechers:</b> {file.num_leechs}"
        except:
            pass
        msg += bottom_status
        return msg
    
    def progress_bar(self, percentage):
        """Returns a progress bar for download
        """
        #percentage is on the scale of 0-1
        comp ="▪️"
        ncomp ="▫️"
        pr = ""

        for i in range(1,11):
            if i <= int(percentage*10):
                pr += comp
            else:
                pr += ncomp
        return pr

    def get_progress_bar_string(self):
        completed = self._update_info.completed_length / 8
        total = self._update_info.total_length / 8
        p = 0 if total == 0 else round(completed * 100 / total)
        p = min(max(p, 0), 100)
        cFull = p // 8
        p_str = '■' * cFull
        p_str += '□' * (12 - cFull)
        p_str = f"[{p_str}]"
        return p_str

    async def remove_dl(self, gid):
        if gid is None:
            gid = self._gid
        aria2 = await self.get_client()
        try:
            download = await self._aloop.run_in_executor(None, aria2.get_download, gid)
            if download.is_waiting:
                aria2.remove([download], force=True, files=True)
                return
            if len(download.followed_by_ids) != 0:
                downloads = aria2.get_downloads(download.followed_by_ids)
                aria2.remove(downloads, force=True, files=True)
                aria2.remove([download], force=True, files=True)
                return
            aria2.remove([download], force=True, files=True)
            LOGGER.info("Download Removed")
        except Exception as e:
            LOGGER.exception(e)
            LOGGER.exception("Failed to Remove Download")
            pass

    def get_gid(self):
        return self._gid

    
    