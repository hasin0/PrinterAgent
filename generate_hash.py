import bcrypt

password = "PROJECT12345678.".encode()
hashed = bcrypt.hashpw(password, bcrypt.gensalt())

print(hashed.decode())