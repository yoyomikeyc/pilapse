from hashlib import md5

def encode_pw(pw):
    """encode clear text string"""
    return md5((pw).encode('utf-8')).hexdigest()


