"""Password/encoding related functions"""
from hashlib import md5

def encode_pw(password):
    """encode clear text string"""
    return md5((password).encode('utf-8')).hexdigest()
