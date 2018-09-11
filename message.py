"""Stupid simple message passing class"""
import pickle


class Message(object):
    """Stupid simple message passing object.  It probbaly has concurency problems."""
    MSG_FN = "messages"
    CAPTURE_ENABLED = "capture_enabled"

    def __init__(self):
        pass

    ##################
    # Private Methods
    ##################
    def __default_message(self):
        msg_dict = {self.CAPTURE_ENABLED : False}
        return msg_dict

    def __send_message(self, msg_dict):
        fd = open(self.MSG_FN, 'wb')
        pickle.dump(msg_dict, fd)
        fd.close()

    def __get_message(self):
        fd = None
        try:
            # we open the file for reading
            fd = open(self.MSG_FN, 'rb')
            # load state
            msg_dict = pickle.load(fd)
        except FileNotFoundError:
            #No prior messages found.
            msg_dict = self.__default_message()
        if fd:
            fd.close()
        return msg_dict

    #################
    # Public Methods
    #################

    def enable_capture(self):
        """signal that capture is enabled"""
        msg_dict = self.__get_message()
        msg_dict[self.CAPTURE_ENABLED] = True
        self.__send_message(msg_dict)

    def disable_capture(self):
        """signal that capture is disabled"""
        msg_dict = self.__get_message()
        msg_dict[self.CAPTURE_ENABLED] = False
        self.__send_message(msg_dict)

    def get_capture_status(self):
        """Returns state of enable_capture"""
        msg_dict = self.__get_message()
        return msg_dict[self.CAPTURE_ENABLED]
    
