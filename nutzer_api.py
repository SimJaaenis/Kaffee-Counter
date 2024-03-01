nutzer = {}			# {192030770: {0: 'Nutzer 1', 1: 0}, 194779730: {0: 'Nutzer 2', 1: 0}}
karte_nutzer = {} 	# {192030770: 'Nutzer 1', 194779730: 'Nutzer 2'}
nutzer_kaffee = {}	# {'Nutzer 1': 0, 'Nutzer 2': 0}
#ausgabe = ""

# def read_Nutzer():
#     with open('NutzerLog.log') as log:
#         lines = [line.rstrip() for line in log]
#     for i in range(len(lines)):
#         entry = lines[i].split(':')
#         key = int(entry[0])
#         name = entry[1]
#         coffee = int(entry[2])
#         nutzer[key] = {}
#         nutzer[key][0] = name
#         nutzer[key][1] = coffee
#     print(nutzer)

def read_Nutzer():
    with open('/Logs/Karte_NutzerID.log') as kn_log:
        kn_lines = [line.rstrip() for line in kn_log]
    for i in range(len(kn_lines)):
        entry = kn_lines[i].split(':')
        card = int(entry[0])
        user = entry[1]
        karte_nutzer[card] = user
    with open('/Logs/NutzerID_Kaffee.log') as nk_log:
        nk_lines = [line.rstrip() for line in nk_log]
    for i in range(len(nk_lines)):
        entry = nk_lines[i].split(':')
        user = entry[0]
        coffee = int(entry[1])
        nutzer_kaffee[user] = coffee 
#     print("karte_nutzer:")
#     print(karte_nutzer)
#     print("nutzer_kaffee:")
#     print(nutzer_kaffee)
#     print()

def update_Nutzer():
    nutzer_kaffee_log = ""
    with open('/Logs/NutzerID_Kaffee.log', 'w') as nk_file:
        for key in nutzer_kaffee.keys():
            zeile = str(key) + ":" + str(nutzer_kaffee[key]) + "\n"
            nutzer_kaffee_log = nutzer_kaffee_log + zeile
        nk_file.write(nutzer_kaffee_log)
#    print(nutzer_kaffee_log)
    
def known_User(card):
    if karte_nutzer.get(card) == None:
        return False
    else:
        return True

def get_Nutzer(card):
    global karte_nutzer
    user = karte_nutzer.get(card)
    if user == None:
        return
    else:
        user = karte_nutzer[card]
    return user

def get_Nutzer_Coffee(card):
    user = karte_nutzer.get(card)
    if user == None:
        return
    else:
        print(user, end = ": ")
        print(str(nutzer_kaffee[user]))
        return str(nutzer_kaffee[user])

def add_Nutzer_Coffee(card):
    user = karte_nutzer.get(card)
    if user == None:
        return
    else:
        nutzer_kaffee[user] += 1
        update_Nutzer()
        print(user, end = ": ")
        print(str(nutzer_kaffee[user]))
        return str(nutzer_kaffee[user])

def add_Nutzer(card):
    karte_nutzer[card] = str(card)
    nutzer_kaffee[str(card)] = 0
    karte_nutzer_log = ""
    with open('/Logs/Karte_NutzerID.log', 'w') as kn_file:
        for key in karte_nutzer.keys():
            zeile = str(key) + ":" + karte_nutzer[key] + "\n"
            karte_nutzer_log = karte_nutzer_log + zeile
        kn_file.write(karte_nutzer_log)
    update_Nutzer()

def reset_Nutzer(card):
    user = karte_nutzer.get(card)
    if user == None:
        return
    else:
        coffee_count = nutzer_kaffee[user]
        nutzer_kaffee[user] = 0
        update_Nutzer()
        print(user, end = ": ")
        print(str(coffee_count))
        return str(coffee_count)


read_Nutzer()
#read_KarteToCoffee()

# print(get_Nutzer_Name(1876543216))
# print(get_Nutzer_Name(18765432166))
# print(get_Nutzer_Coffee(1876543216))
# print(add_Nutzer_Coffee(1876543216))
# print(add_Nutzer_Coffee(1876543216))
# print(add_Nutzer_Coffee(1876543216))
