from reedsolo import RSCodec
from PIL import Image
from dataclasses import dataclass

@dataclass
class QRCodeData:
    final_bit_stream: str
    version: int
    error_correction_level: str
    encoding_mode: str



def is_qr_kanji_character(char: str) -> bool:
    try:
        sjis_bytes = char.encode('shift_jis')
    except UnicodeEncodeError:
        return False

    if len(sjis_bytes) != 2:
        return False

    code_point = (sjis_bytes[0] << 8) | sjis_bytes[1]
    return (0x8140 <= code_point <= 0x9FFC) or (0xE040 <= code_point <= 0xEBBF)


def is_qr_kanji(data: str) -> bool:
    return bool(data) and all(is_qr_kanji_character(char) for char in data)


def select_encoding_mode(data: str) -> str:
    if is_qr_kanji(data):
        return 'kanji'
    elif all(char in '0123456789' for char in data):
        return 'numeric'
    elif all(char in '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ $%*+-./:' for char in data):
        return 'alphanumeric'
    else:
        return 'byte'


def select_qr_code_version(data_length: int, encoding_mode: str, error_correction_level: str, qr_capacity: dict) -> int:
    for version in range(1, 41):
        if version in qr_capacity and error_correction_level in qr_capacity[version]:
            capacity = qr_capacity[version][error_correction_level][encoding_mode]
            if data_length <= capacity:
                return version
    return None


def get_character_count_bit_length(version: int, mode: str, qr_character_count_bits: dict) -> int:
     if 1 <= version <= 9:
          return qr_character_count_bits[(1, 9)][mode]
     if 10 <= version <= 26:
          return qr_character_count_bits[(10, 26)][mode]
     return qr_character_count_bits[(27, 40)][mode]


def kanji_char_to_bits(char: str) -> str:
    sjis = char.encode('shift_jis')
    if len(sjis) != 2:
        raise ValueError("Not encodable in QR Kanji (needs 2-byte Shift_JIS)")
    
    val = (sjis[0] << 8) | sjis[1]
    if 0x8140 <= val <= 0x9FFC:
        sub = val - 0x8140

    elif 0xE040 <= val <= 0xEBBF:
        sub = val - 0xC140

    else:
        raise ValueError("Character not in QR Kanji ranges")
    
    encoded = ((sub >> 8) * 0xC0) + (sub & 0xFF)
    return format(encoded, '013b')


def encode_data(data: str, mode: str, alphanumeric_table: dict) -> str:
    if mode == 'numeric':
        # Split numeric data into groups of 3 digits, last group can be 1 or 2 digits
        split_data = [data[i:i+3] for i in range(0, len(data), 3)]
        # Encode each group of digits into binary: 3 digits -> 10 bits, 2 digits -> 7 bits, 1 digit -> 4 bits
        binary_data = [format(int(group), '010b') if len(group) == 3 else format(int(group), '0' + str(len(group) * 3 + 1) + 'b') for group in split_data]
        return ''.join(binary_data)
    
    elif mode == 'alphanumeric':
        # Split alphanumeric data into groups of 2 characters, last group can be 1 character
        split_data = [data[i:i+2] for i in range(0, len(data), 2)]

        # Get number representation of first character, multiply by 45 and add number representation of second character, 
        # encode into binary: 2 chars -> 11 bits, 1 char -> 6 bits (with 1 char just translate the number representation into 6 bits)
        binary_data = []

        for group in split_data:
            if len(group) == 2:
                first_value = alphanumeric_table.get(group[0])
                second_value = alphanumeric_table.get(group[1])

                numeric_value = first_value * 45 + second_value
                binary_data.append(format(numeric_value, '011b'))
            else:
                single_value = alphanumeric_table.get(group[0])

                binary_data.append(format(single_value, '06b'))
        return ''.join(binary_data)
    
    elif mode == 'byte':
        # Convert input data to ISO 8859-1 otherwise into UTF-8
        try:
            byte_data = data.encode('iso-8859-1')
            print("Data encoded in ISO 8859-1.")
        except UnicodeEncodeError:
            byte_data = data.encode('utf-8')
            print("Warning: Data contains characters outside ISO 8859-1, encoded in UTF-8 instead.")
       
        # Encode each byte into 8 bits
        binary_data = [format(byte, '08b') for byte in byte_data]
        
        return ''.join(binary_data)
    
    elif mode == 'kanji':
        # Encode kanji characters using Shift_JIS and convert to 13-bit binary
        return ''.join(kanji_char_to_bits(character) for character in data)
    else:
        raise ValueError("Unsupported encoding mode")


def add_padding_bits(encoded_data: str, version: int, error_correction_level: str, qr_error_correction_table: dict) -> str:
    data_bit_capacity = qr_error_correction_table[version][error_correction_level]['total_data_codewords'] * 8
    remaining_bits = data_bit_capacity - len(encoded_data)
    padding_bits = ''

    # Add terminator bits (up to 4 bits of zeros)
    if remaining_bits > 0:
        terminator_length = min(4, remaining_bits)
        padding_bits += '0' * terminator_length
        remaining_bits -= terminator_length

    # Add zero padding bits to make the length a multiple of 8
    if (len(encoded_data) + len(padding_bits)) % 8 != 0:
        padding_needed = 8 - ((len(encoded_data) + len(padding_bits)) % 8)
        padding_bits += '0' * padding_needed
        remaining_bits -= padding_needed

    # Add pad codewords (alternating 11101100 and 00010001) to fill remaining bytes
    pad_codewords = ['11101100', '00010001']
    i = 0
    while remaining_bits >= 8:
        padding_bits += pad_codewords[i % 2]
        i += 1
        remaining_bits -= 8

    return padding_bits


def generate_error_correction(blocks: dict, ec_codewords_per_block: int) -> dict:
    rsc = RSCodec(ec_codewords_per_block)
    ec_blocks = {}
    
    for block_name, block_data in blocks.items():
        # Convert block_data (list of 8-bit strings) to bytes
        data_bytes = bytes(int(byte_str, 2) for byte_str in block_data)
        
        # Encode and extract EC codewords
        encoded = rsc.encode(data_bytes)
        ec_codewords = encoded[-ec_codewords_per_block:]
        
        # Store as binary strings
        ec_blocks[block_name] = [format(byte, '08b') for byte in ec_codewords]
    
    return ec_blocks


def generate_error_correction_codewords(encoded_data: str, version: int, error_correction_level: str, qr_error_correction_table: dict) -> tuple:

    # Get error correction parameters from the table
    ec_info = qr_error_correction_table[version][error_correction_level]
    ec_codewords_per_block = ec_info['ec_codewords_per_block']
    blocks_group1 = ec_info['blocks_group1']
    data_codewords_group1 = ec_info['data_codewords_group1']
    blocks_group2 = ec_info['blocks_group2']
    data_codewords_group2 = ec_info['data_codewords_group2']

    # Split encoded data into blocks according to the error correction parameters
    data_codewords = [encoded_data[i:i+8] for i in range(0, len(encoded_data), 8)]
    blocks = {}
    block_index = 0
    codeword_index = 0

    # Add blocks from group 1
    for _ in range(blocks_group1):
        blocks[f'block{block_index}'] = data_codewords[codeword_index:codeword_index+data_codewords_group1]
        codeword_index += data_codewords_group1
        block_index += 1

    # Add blocks from group 2
    for _ in range(blocks_group2):
        blocks[f'block{block_index}'] = data_codewords[codeword_index:codeword_index+data_codewords_group2]
        codeword_index += data_codewords_group2
        block_index += 1

    # Generate error correction codewords
    ec_blocks = generate_error_correction(blocks, ec_codewords_per_block)

    return blocks, ec_blocks


def create_final_bit_stream(data_codewords: dict, error_correction_codewords: dict, qr_code_version: int, qr_remainder_bits: dict) -> str:
    final_bit_stream = ''

    max_data_length = max(len(block) for block in data_codewords.values())

    # Interleave data codewords from all blocks
    for i in range(max_data_length):
        for block in data_codewords.values():
            if i < len(block):
                final_bit_stream += block[i]

    # Get length of the first block of error correction codewords (all blocks have the same number of EC codewords)
    max_ec_length = len(next(iter(error_correction_codewords.values())))

    # Interleave error correction codewords from all blocks
    for i in range(max_ec_length):
        for block in error_correction_codewords.values():
            if i < len(block):
                final_bit_stream += block[i]

    # Add remainder bits if necessary
    remainder_bits = qr_remainder_bits.get(qr_code_version, 0)
    final_bit_stream += '0' * remainder_bits

    return final_bit_stream


def create_qr_code_message(input_data: str, qr_code_version: int=None, error_correction_level: str="L"):

    ENCODING_MODE_INDICATORS = {
        "numeric": "0001",
        "alphanumeric": "0010",
        "byte": "0100",
        "kanji": "1000"
    }

    QR_CAPACITIES = {
    1: {'L': {'numeric': 41, 'alphanumeric': 25, 'byte': 17, 'kanji': 10},
        'M': {'numeric': 34, 'alphanumeric': 20, 'byte': 14, 'kanji': 8},
        'Q': {'numeric': 27, 'alphanumeric': 16, 'byte': 11, 'kanji': 7},
        'H': {'numeric': 17, 'alphanumeric': 10, 'byte': 7, 'kanji': 4}},
    2: {'L': {'numeric': 77, 'alphanumeric': 47, 'byte': 32, 'kanji': 20},
        'M': {'numeric': 63, 'alphanumeric': 38, 'byte': 26, 'kanji': 16},
        'Q': {'numeric': 48, 'alphanumeric': 29, 'byte': 20, 'kanji': 12},
        'H': {'numeric': 34, 'alphanumeric': 20, 'byte': 14, 'kanji': 8}},
    3: {'L': {'numeric': 127, 'alphanumeric': 77, 'byte': 53, 'kanji': 32},
        'M': {'numeric': 101, 'alphanumeric': 61, 'byte': 42, 'kanji': 26},
        'Q': {'numeric': 77, 'alphanumeric': 47, 'byte': 32, 'kanji': 20},
        'H': {'numeric': 58, 'alphanumeric': 35, 'byte': 24, 'kanji': 15}},
    4: {'L': {'numeric': 187, 'alphanumeric': 114, 'byte': 78, 'kanji': 48},
        'M': {'numeric': 149, 'alphanumeric': 90, 'byte': 62, 'kanji': 38},
        'Q': {'numeric': 111, 'alphanumeric': 67, 'byte': 46, 'kanji': 28},
        'H': {'numeric': 82, 'alphanumeric': 50, 'byte': 34, 'kanji': 21}},
    5: {'L': {'numeric': 255, 'alphanumeric': 154, 'byte': 106, 'kanji': 65},
        'M': {'numeric': 202, 'alphanumeric': 122, 'byte': 84, 'kanji': 52},
        'Q': {'numeric': 144, 'alphanumeric': 87, 'byte': 60, 'kanji': 37},
        'H': {'numeric': 106, 'alphanumeric': 64, 'byte': 44, 'kanji': 27}},
    6: {'L': {'numeric': 322, 'alphanumeric': 195, 'byte': 134, 'kanji': 82},
        'M': {'numeric': 255, 'alphanumeric': 154, 'byte': 106, 'kanji': 65},
        'Q': {'numeric': 178, 'alphanumeric': 108, 'byte': 74, 'kanji': 45},
        'H': {'numeric': 139, 'alphanumeric': 84, 'byte': 58, 'kanji': 36}},
    7: {'L': {'numeric': 370, 'alphanumeric': 224, 'byte': 154, 'kanji': 95},
        'M': {'numeric': 293, 'alphanumeric': 178, 'byte': 122, 'kanji': 75},
        'Q': {'numeric': 207, 'alphanumeric': 125, 'byte': 86, 'kanji': 53},
        'H': {'numeric': 154, 'alphanumeric': 93, 'byte': 64, 'kanji': 39}},
    8: {'L': {'numeric': 461, 'alphanumeric': 279, 'byte': 192, 'kanji': 118},
        'M': {'numeric': 365, 'alphanumeric': 221, 'byte': 152, 'kanji': 93},
        'Q': {'numeric': 259, 'alphanumeric': 157, 'byte': 108, 'kanji': 66},
        'H': {'numeric': 202, 'alphanumeric': 122, 'byte': 84, 'kanji': 52}},
    9: {'L': {'numeric': 552, 'alphanumeric': 335, 'byte': 230, 'kanji': 141},
        'M': {'numeric': 432, 'alphanumeric': 262, 'byte': 180, 'kanji': 111},
        'Q': {'numeric': 312, 'alphanumeric': 189, 'byte': 130, 'kanji': 80},
        'H': {'numeric': 235, 'alphanumeric': 143, 'byte': 98, 'kanji': 60}},
    10: {'L': {'numeric': 652, 'alphanumeric': 395, 'byte': 271, 'kanji': 167},
        'M': {'numeric': 513, 'alphanumeric': 311, 'byte': 213, 'kanji': 131},
        'Q': {'numeric': 364, 'alphanumeric': 221, 'byte': 151, 'kanji': 93},
        'H': {'numeric': 288, 'alphanumeric': 174, 'byte': 119, 'kanji': 74}},
    11: {'L': {'numeric': 772, 'alphanumeric': 468, 'byte': 321, 'kanji': 198},
        'M': {'numeric': 604, 'alphanumeric': 366, 'byte': 251, 'kanji': 155},
        'Q': {'numeric': 427, 'alphanumeric': 259, 'byte': 177, 'kanji': 109},
        'H': {'numeric': 331, 'alphanumeric': 200, 'byte': 137, 'kanji': 85}},
    12: {'L': {'numeric': 883, 'alphanumeric': 535, 'byte': 367, 'kanji': 226},
        'M': {'numeric': 691, 'alphanumeric': 419, 'byte': 287, 'kanji': 177},
        'Q': {'numeric': 489, 'alphanumeric': 296, 'byte': 203, 'kanji': 125},
        'H': {'numeric': 374, 'alphanumeric': 227, 'byte': 155, 'kanji': 96}},
    13: {'L': {'numeric': 1022, 'alphanumeric': 619, 'byte': 425, 'kanji': 262},
        'M': {'numeric': 796, 'alphanumeric': 483, 'byte': 331, 'kanji': 204},
        'Q': {'numeric': 580, 'alphanumeric': 352, 'byte': 241, 'kanji': 149},
        'H': {'numeric': 427, 'alphanumeric': 259, 'byte': 177, 'kanji': 109}},
    14: {'L': {'numeric': 1101, 'alphanumeric': 667, 'byte': 458, 'kanji': 282},
        'M': {'numeric': 871, 'alphanumeric': 528, 'byte': 362, 'kanji': 223},
        'Q': {'numeric': 621, 'alphanumeric': 376, 'byte': 258, 'kanji': 159},
        'H': {'numeric': 468, 'alphanumeric': 283, 'byte': 194, 'kanji': 120}},
    15: {'L': {'numeric': 1250, 'alphanumeric': 758, 'byte': 520, 'kanji': 320},
        'M': {'numeric': 991, 'alphanumeric': 600, 'byte': 412, 'kanji': 254},
        'Q': {'numeric': 703, 'alphanumeric': 426, 'byte': 292, 'kanji': 180},
        'H': {'numeric': 530, 'alphanumeric': 321, 'byte': 220, 'kanji': 136}},
    16: {'L': {'numeric': 1408, 'alphanumeric': 854, 'byte': 586, 'kanji': 361},
        'M': {'numeric': 1082, 'alphanumeric': 656, 'byte': 450, 'kanji': 277},
        'Q': {'numeric': 775, 'alphanumeric': 470, 'byte': 322, 'kanji': 198},
        'H': {'numeric': 602, 'alphanumeric': 365, 'byte': 250, 'kanji': 154}},
    17: {'L': {'numeric': 1548, 'alphanumeric': 938, 'byte': 644, 'kanji': 397},
        'M': {'numeric': 1212, 'alphanumeric': 734, 'byte': 504, 'kanji': 310},
        'Q': {'numeric': 876, 'alphanumeric': 531, 'byte': 364, 'kanji': 224},
        'H': {'numeric': 674, 'alphanumeric': 408, 'byte': 280, 'kanji': 173}},
    18: {'L': {'numeric': 1725, 'alphanumeric': 1046, 'byte': 718, 'kanji': 442},
        'M': {'numeric': 1346, 'alphanumeric': 816, 'byte': 560, 'kanji': 345},
        'Q': {'numeric': 948, 'alphanumeric': 574, 'byte': 394, 'kanji': 243},
        'H': {'numeric': 746, 'alphanumeric': 452, 'byte': 310, 'kanji': 191}},
    19: {'L': {'numeric': 1903, 'alphanumeric': 1153, 'byte': 792, 'kanji': 488},
        'M': {'numeric': 1500, 'alphanumeric': 909, 'byte': 624, 'kanji': 384},
        'Q': {'numeric': 1063, 'alphanumeric': 644, 'byte': 442, 'kanji': 272},
        'H': {'numeric': 813, 'alphanumeric': 493, 'byte': 338, 'kanji': 208}},
    20: {'L': {'numeric': 2061, 'alphanumeric': 1249, 'byte': 858, 'kanji': 528},
        'M': {'numeric': 1600, 'alphanumeric': 970, 'byte': 666, 'kanji': 410},
        'Q': {'numeric': 1159, 'alphanumeric': 702, 'byte': 482, 'kanji': 297},
        'H': {'numeric': 919, 'alphanumeric': 557, 'byte': 382, 'kanji': 235}},
    21: {'L': {'numeric': 2232, 'alphanumeric': 1352, 'byte': 929, 'kanji': 572},
        'M': {'numeric': 1708, 'alphanumeric': 1035, 'byte': 711, 'kanji': 438},
        'Q': {'numeric': 1224, 'alphanumeric': 742, 'byte': 509, 'kanji': 314},
        'H': {'numeric': 969, 'alphanumeric': 587, 'byte': 403, 'kanji': 248}},
    22: {'L': {'numeric': 2409, 'alphanumeric': 1460, 'byte': 1003, 'kanji': 618},
        'M': {'numeric': 1872, 'alphanumeric': 1134, 'byte': 779, 'kanji': 480},
        'Q': {'numeric': 1358, 'alphanumeric': 823, 'byte': 565, 'kanji': 348},
        'H': {'numeric': 1056, 'alphanumeric': 640, 'byte': 439, 'kanji': 270}},
    23: {'L': {'numeric': 2620, 'alphanumeric': 1588, 'byte': 1091, 'kanji': 672},
        'M': {'numeric': 2059, 'alphanumeric': 1248, 'byte': 857, 'kanji': 528},
        'Q': {'numeric': 1468, 'alphanumeric': 890, 'byte': 611, 'kanji': 376},
        'H': {'numeric': 1108, 'alphanumeric': 672, 'byte': 461, 'kanji': 284}},
    24: {'L': {'numeric': 2812, 'alphanumeric': 1704, 'byte': 1171, 'kanji': 721},
        'M': {'numeric': 2188, 'alphanumeric': 1326, 'byte': 911, 'kanji': 561},
        'Q': {'numeric': 1588, 'alphanumeric': 963, 'byte': 661, 'kanji': 407},
        'H': {'numeric': 1228, 'alphanumeric': 744, 'byte': 511, 'kanji': 315}},
    25: {'L': {'numeric': 3057, 'alphanumeric': 1853, 'byte': 1273, 'kanji': 784},
        'M': {'numeric': 2395, 'alphanumeric': 1451, 'byte': 997, 'kanji': 614},
        'Q': {'numeric': 1718, 'alphanumeric': 1041, 'byte': 715, 'kanji': 440},
        'H': {'numeric': 1286, 'alphanumeric': 779, 'byte': 535, 'kanji': 330}},
    26: {'L': {'numeric': 3283, 'alphanumeric': 1990, 'byte': 1367, 'kanji': 842},
        'M': {'numeric': 2544, 'alphanumeric': 1542, 'byte': 1059, 'kanji': 652},
        'Q': {'numeric': 1804, 'alphanumeric': 1094, 'byte': 751, 'kanji': 462},
        'H': {'numeric': 1425, 'alphanumeric': 864, 'byte': 593, 'kanji': 365}},
    27: {'L': {'numeric': 3517, 'alphanumeric': 2132, 'byte': 1465, 'kanji': 902},
        'M': {'numeric': 2701, 'alphanumeric': 1637, 'byte': 1125, 'kanji': 692},
        'Q': {'numeric': 1933, 'alphanumeric': 1172, 'byte': 805, 'kanji': 496},
        'H': {'numeric': 1501, 'alphanumeric': 910, 'byte': 625, 'kanji': 385}},
    28: {'L': {'numeric': 3669, 'alphanumeric': 2223, 'byte': 1528, 'kanji': 940},
        'M': {'numeric': 2857, 'alphanumeric': 1732, 'byte': 1190, 'kanji': 732},
        'Q': {'numeric': 2085, 'alphanumeric': 1263, 'byte': 868, 'kanji': 534},
        'H': {'numeric': 1581, 'alphanumeric': 958, 'byte': 658, 'kanji': 405}},
    29: {'L': {'numeric': 3909, 'alphanumeric': 2369, 'byte': 1628, 'kanji': 1002},
        'M': {'numeric': 3035, 'alphanumeric': 1839, 'byte': 1264, 'kanji': 778},
        'Q': {'numeric': 2181, 'alphanumeric': 1322, 'byte': 908, 'kanji': 559},
        'H': {'numeric': 1677, 'alphanumeric': 1016, 'byte': 698, 'kanji': 430}},
    30: {'L': {'numeric': 4158, 'alphanumeric': 2520, 'byte': 1732, 'kanji': 1066},
        'M': {'numeric': 3289, 'alphanumeric': 1994, 'byte': 1370, 'kanji': 843},
        'Q': {'numeric': 2358, 'alphanumeric': 1429, 'byte': 982, 'kanji': 604},
        'H': {'numeric': 1782, 'alphanumeric': 1080, 'byte': 742, 'kanji': 457}},
    31: {'L': {'numeric': 4417, 'alphanumeric': 2677, 'byte': 1840, 'kanji': 1132},
        'M': {'numeric': 3486, 'alphanumeric': 2113, 'byte': 1452, 'kanji': 894},
        'Q': {'numeric': 2473, 'alphanumeric': 1499, 'byte': 1030, 'kanji': 634},
        'H': {'numeric': 1897, 'alphanumeric': 1150, 'byte': 790, 'kanji': 486}},
    32: {'L': {'numeric': 4686, 'alphanumeric': 2840, 'byte': 1952, 'kanji': 1201},
        'M': {'numeric': 3693, 'alphanumeric': 2238, 'byte': 1538, 'kanji': 947},
        'Q': {'numeric': 2670, 'alphanumeric': 1618, 'byte': 1112, 'kanji': 684},
        'H': {'numeric': 2022, 'alphanumeric': 1226, 'byte': 842, 'kanji': 518}},
    33: {'L': {'numeric': 4965, 'alphanumeric': 3009, 'byte': 2068, 'kanji': 1273},
        'M': {'numeric': 3909, 'alphanumeric': 2369, 'byte': 1628, 'kanji': 1002},
        'Q': {'numeric': 2805, 'alphanumeric': 1700, 'byte': 1168, 'kanji': 719},
        'H': {'numeric': 2157, 'alphanumeric': 1307, 'byte': 898, 'kanji': 553}},
    34: {'L': {'numeric': 5253, 'alphanumeric': 3183, 'byte': 2188, 'kanji': 1347},
        'M': {'numeric': 4134, 'alphanumeric': 2506, 'byte': 1722, 'kanji': 1060},
        'Q': {'numeric': 2949, 'alphanumeric': 1787, 'byte': 1228, 'kanji': 756},
        'H': {'numeric': 2301, 'alphanumeric': 1394, 'byte': 958, 'kanji': 590}},
    35: {'L': {'numeric': 5529, 'alphanumeric': 3351, 'byte': 2303, 'kanji': 1417},
        'M': {'numeric': 4343, 'alphanumeric': 2632, 'byte': 1809, 'kanji': 1113},
        'Q': {'numeric': 3081, 'alphanumeric': 1867, 'byte': 1283, 'kanji': 790},
        'H': {'numeric': 2361, 'alphanumeric': 1431, 'byte': 983, 'kanji': 605}},
    36: {'L': {'numeric': 5836, 'alphanumeric': 3537, 'byte': 2431, 'kanji': 1496},
        'M': {'numeric': 4588, 'alphanumeric': 2780, 'byte': 1911, 'kanji': 1176},
        'Q': {'numeric': 3244, 'alphanumeric': 1966, 'byte': 1351, 'kanji': 832},
        'H': {'numeric': 2524, 'alphanumeric': 1530, 'byte': 1051, 'kanji': 647}},
    37: {'L': {'numeric': 6153, 'alphanumeric': 3729, 'byte': 2563, 'kanji': 1577},
        'M': {'numeric': 4775, 'alphanumeric': 2894, 'byte': 1989, 'kanji': 1224},
        'Q': {'numeric': 3417, 'alphanumeric': 2071, 'byte': 1423, 'kanji': 876},
        'H': {'numeric': 2625, 'alphanumeric': 1591, 'byte': 1093, 'kanji': 673}},
    38: {'L': {'numeric': 6479, 'alphanumeric': 3927, 'byte': 2699, 'kanji': 1661},
        'M': {'numeric': 5039, 'alphanumeric': 3054, 'byte': 2099, 'kanji': 1292},
        'Q': {'numeric': 3599, 'alphanumeric': 2181, 'byte': 1499, 'kanji': 923},
        'H': {'numeric': 2735, 'alphanumeric': 1658, 'byte': 1139, 'kanji': 701}},
    39: {'L': {'numeric': 6743, 'alphanumeric': 4087, 'byte': 2809, 'kanji': 1729},
        'M': {'numeric': 5313, 'alphanumeric': 3220, 'byte': 2213, 'kanji': 1362},
        'Q': {'numeric': 3791, 'alphanumeric': 2298, 'byte': 1579, 'kanji': 972},
        'H': {'numeric': 2927, 'alphanumeric': 1774, 'byte': 1219, 'kanji': 750}},
    40: {'L': {'numeric': 7089, 'alphanumeric': 4296, 'byte': 2953, 'kanji': 1817},
        'M': {'numeric': 5596, 'alphanumeric': 3391, 'byte': 2331, 'kanji': 1435},
        'Q': {'numeric': 3993, 'alphanumeric': 2420, 'byte': 1663, 'kanji': 1024},
        'H': {'numeric': 3057, 'alphanumeric': 1852, 'byte': 1273, 'kanji': 784}}}

    # QR Error Correction Table with data codewords and block information for each version and EC level
    QR_ERROR_CORRECTION_TABLE = {
        1: {'L': {'total_data_codewords': 19, 'ec_codewords_per_block': 7, 'blocks_group1': 1, 'data_codewords_group1': 19, 'blocks_group2': 0, 'data_codewords_group2': 0},
            'M': {'total_data_codewords': 16, 'ec_codewords_per_block': 10, 'blocks_group1': 1, 'data_codewords_group1': 16, 'blocks_group2': 0, 'data_codewords_group2': 0},
            'Q': {'total_data_codewords': 13, 'ec_codewords_per_block': 13, 'blocks_group1': 1, 'data_codewords_group1': 13, 'blocks_group2': 0, 'data_codewords_group2': 0},
            'H': {'total_data_codewords': 9, 'ec_codewords_per_block': 17, 'blocks_group1': 1, 'data_codewords_group1': 9, 'blocks_group2': 0, 'data_codewords_group2': 0}},
        2: {'L': {'total_data_codewords': 34, 'ec_codewords_per_block': 10, 'blocks_group1': 1, 'data_codewords_group1': 34, 'blocks_group2': 0, 'data_codewords_group2': 0},
            'M': {'total_data_codewords': 28, 'ec_codewords_per_block': 16, 'blocks_group1': 1, 'data_codewords_group1': 28, 'blocks_group2': 0, 'data_codewords_group2': 0},
            'Q': {'total_data_codewords': 22, 'ec_codewords_per_block': 22, 'blocks_group1': 1, 'data_codewords_group1': 22, 'blocks_group2': 0, 'data_codewords_group2': 0},
            'H': {'total_data_codewords': 16, 'ec_codewords_per_block': 28, 'blocks_group1': 1, 'data_codewords_group1': 16, 'blocks_group2': 0, 'data_codewords_group2': 0}},
        3: {'L': {'total_data_codewords': 55, 'ec_codewords_per_block': 15, 'blocks_group1': 1, 'data_codewords_group1': 55, 'blocks_group2': 0, 'data_codewords_group2': 0},
            'M': {'total_data_codewords': 44, 'ec_codewords_per_block': 26, 'blocks_group1': 1, 'data_codewords_group1': 44, 'blocks_group2': 0, 'data_codewords_group2': 0},
            'Q': {'total_data_codewords': 34, 'ec_codewords_per_block': 18, 'blocks_group1': 2, 'data_codewords_group1': 17, 'blocks_group2': 0, 'data_codewords_group2': 0},
            'H': {'total_data_codewords': 26, 'ec_codewords_per_block': 22, 'blocks_group1': 2, 'data_codewords_group1': 13, 'blocks_group2': 0, 'data_codewords_group2': 0}},
        4: {'L': {'total_data_codewords': 80, 'ec_codewords_per_block': 20, 'blocks_group1': 1, 'data_codewords_group1': 80, 'blocks_group2': 0, 'data_codewords_group2': 0},
            'M': {'total_data_codewords': 64, 'ec_codewords_per_block': 18, 'blocks_group1': 2, 'data_codewords_group1': 32, 'blocks_group2': 0, 'data_codewords_group2': 0},
            'Q': {'total_data_codewords': 48, 'ec_codewords_per_block': 26, 'blocks_group1': 2, 'data_codewords_group1': 24, 'blocks_group2': 0, 'data_codewords_group2': 0},
            'H': {'total_data_codewords': 36, 'ec_codewords_per_block': 16, 'blocks_group1': 4, 'data_codewords_group1': 9, 'blocks_group2': 0, 'data_codewords_group2': 0}},
        5: {'L': {'total_data_codewords': 108, 'ec_codewords_per_block': 26, 'blocks_group1': 1, 'data_codewords_group1': 108, 'blocks_group2': 0, 'data_codewords_group2': 0},
            'M': {'total_data_codewords': 86, 'ec_codewords_per_block': 24, 'blocks_group1': 2, 'data_codewords_group1': 43, 'blocks_group2': 0, 'data_codewords_group2': 0},
            'Q': {'total_data_codewords': 62, 'ec_codewords_per_block': 18, 'blocks_group1': 2, 'data_codewords_group1': 15, 'blocks_group2': 2, 'data_codewords_group2': 16},
            'H': {'total_data_codewords': 46, 'ec_codewords_per_block': 22, 'blocks_group1': 2, 'data_codewords_group1': 11, 'blocks_group2': 2, 'data_codewords_group2': 12}},
        6: {'L': {'total_data_codewords': 136, 'ec_codewords_per_block': 18, 'blocks_group1': 2, 'data_codewords_group1': 68, 'blocks_group2': 0, 'data_codewords_group2': 0},
            'M': {'total_data_codewords': 108, 'ec_codewords_per_block': 16, 'blocks_group1': 4, 'data_codewords_group1': 27, 'blocks_group2': 0, 'data_codewords_group2': 0},
            'Q': {'total_data_codewords': 76, 'ec_codewords_per_block': 24, 'blocks_group1': 4, 'data_codewords_group1': 19, 'blocks_group2': 0, 'data_codewords_group2': 0},
            'H': {'total_data_codewords': 60, 'ec_codewords_per_block': 28, 'blocks_group1': 4, 'data_codewords_group1': 15, 'blocks_group2': 0, 'data_codewords_group2': 0}},
        7: {'L': {'total_data_codewords': 156, 'ec_codewords_per_block': 20, 'blocks_group1': 2, 'data_codewords_group1': 78, 'blocks_group2': 0, 'data_codewords_group2': 0},
            'M': {'total_data_codewords': 124, 'ec_codewords_per_block': 18, 'blocks_group1': 4, 'data_codewords_group1': 31, 'blocks_group2': 0, 'data_codewords_group2': 0},
            'Q': {'total_data_codewords': 88, 'ec_codewords_per_block': 18, 'blocks_group1': 2, 'data_codewords_group1': 14, 'blocks_group2': 4, 'data_codewords_group2': 15},
            'H': {'total_data_codewords': 66, 'ec_codewords_per_block': 26, 'blocks_group1': 4, 'data_codewords_group1': 13, 'blocks_group2': 1, 'data_codewords_group2': 14}},
        8: {'L': {'total_data_codewords': 194, 'ec_codewords_per_block': 24, 'blocks_group1': 2, 'data_codewords_group1': 97, 'blocks_group2': 0, 'data_codewords_group2': 0},
            'M': {'total_data_codewords': 154, 'ec_codewords_per_block': 22, 'blocks_group1': 2, 'data_codewords_group1': 38, 'blocks_group2': 2, 'data_codewords_group2': 39},
            'Q': {'total_data_codewords': 110, 'ec_codewords_per_block': 22, 'blocks_group1': 4, 'data_codewords_group1': 18, 'blocks_group2': 2, 'data_codewords_group2': 19},
            'H': {'total_data_codewords': 86, 'ec_codewords_per_block': 26, 'blocks_group1': 4, 'data_codewords_group1': 14, 'blocks_group2': 2, 'data_codewords_group2': 15}},
        9: {'L': {'total_data_codewords': 232, 'ec_codewords_per_block': 30, 'blocks_group1': 2, 'data_codewords_group1': 116, 'blocks_group2': 0, 'data_codewords_group2': 0},
            'M': {'total_data_codewords': 182, 'ec_codewords_per_block': 22, 'blocks_group1': 3, 'data_codewords_group1': 36, 'blocks_group2': 2, 'data_codewords_group2': 37},
            'Q': {'total_data_codewords': 132, 'ec_codewords_per_block': 20, 'blocks_group1': 4, 'data_codewords_group1': 16, 'blocks_group2': 4, 'data_codewords_group2': 17},
            'H': {'total_data_codewords': 100, 'ec_codewords_per_block': 24, 'blocks_group1': 4, 'data_codewords_group1': 12, 'blocks_group2': 4, 'data_codewords_group2': 13}},
        10: {'L': {'total_data_codewords': 274, 'ec_codewords_per_block': 18, 'blocks_group1': 2, 'data_codewords_group1': 68, 'blocks_group2': 2, 'data_codewords_group2': 69},
            'M': {'total_data_codewords': 216, 'ec_codewords_per_block': 26, 'blocks_group1': 4, 'data_codewords_group1': 43, 'blocks_group2': 1, 'data_codewords_group2': 44},
            'Q': {'total_data_codewords': 154, 'ec_codewords_per_block': 24, 'blocks_group1': 6, 'data_codewords_group1': 19, 'blocks_group2': 2, 'data_codewords_group2': 20},
            'H': {'total_data_codewords': 122, 'ec_codewords_per_block': 28, 'blocks_group1': 6, 'data_codewords_group1': 15, 'blocks_group2': 2, 'data_codewords_group2': 16}},
        11: {'L': {'total_data_codewords': 324, 'ec_codewords_per_block': 20, 'blocks_group1': 4, 'data_codewords_group1': 81, 'blocks_group2': 0, 'data_codewords_group2': 0},
            'M': {'total_data_codewords': 254, 'ec_codewords_per_block': 30, 'blocks_group1': 1, 'data_codewords_group1': 50, 'blocks_group2': 4, 'data_codewords_group2': 51},
            'Q': {'total_data_codewords': 180, 'ec_codewords_per_block': 28, 'blocks_group1': 4, 'data_codewords_group1': 22, 'blocks_group2': 4, 'data_codewords_group2': 23},
            'H': {'total_data_codewords': 140, 'ec_codewords_per_block': 24, 'blocks_group1': 3, 'data_codewords_group1': 12, 'blocks_group2': 8, 'data_codewords_group2': 13}},
        12: {'L': {'total_data_codewords': 370, 'ec_codewords_per_block': 24, 'blocks_group1': 2, 'data_codewords_group1': 92, 'blocks_group2': 2, 'data_codewords_group2': 93},
            'M': {'total_data_codewords': 290, 'ec_codewords_per_block': 22, 'blocks_group1': 6, 'data_codewords_group1': 36, 'blocks_group2': 2, 'data_codewords_group2': 37},
            'Q': {'total_data_codewords': 206, 'ec_codewords_per_block': 26, 'blocks_group1': 4, 'data_codewords_group1': 20, 'blocks_group2': 6, 'data_codewords_group2': 21},
            'H': {'total_data_codewords': 158, 'ec_codewords_per_block': 28, 'blocks_group1': 7, 'data_codewords_group1': 14, 'blocks_group2': 4, 'data_codewords_group2': 15}},
        13: {'L': {'total_data_codewords': 428, 'ec_codewords_per_block': 26, 'blocks_group1': 4, 'data_codewords_group1': 107, 'blocks_group2': 0, 'data_codewords_group2': 0},
            'M': {'total_data_codewords': 334, 'ec_codewords_per_block': 22, 'blocks_group1': 8, 'data_codewords_group1': 37, 'blocks_group2': 1, 'data_codewords_group2': 38},
            'Q': {'total_data_codewords': 244, 'ec_codewords_per_block': 24, 'blocks_group1': 8, 'data_codewords_group1': 20, 'blocks_group2': 4, 'data_codewords_group2': 21},
            'H': {'total_data_codewords': 180, 'ec_codewords_per_block': 22, 'blocks_group1': 12, 'data_codewords_group1': 11, 'blocks_group2': 4, 'data_codewords_group2': 12}},
        14: {'L': {'total_data_codewords': 461, 'ec_codewords_per_block': 30, 'blocks_group1': 3, 'data_codewords_group1': 115, 'blocks_group2': 1, 'data_codewords_group2': 116},
            'M': {'total_data_codewords': 365, 'ec_codewords_per_block': 24, 'blocks_group1': 4, 'data_codewords_group1': 40, 'blocks_group2': 5, 'data_codewords_group2': 41},
            'Q': {'total_data_codewords': 261, 'ec_codewords_per_block': 20, 'blocks_group1': 11, 'data_codewords_group1': 16, 'blocks_group2': 5, 'data_codewords_group2': 17},
            'H': {'total_data_codewords': 197, 'ec_codewords_per_block': 24, 'blocks_group1': 11, 'data_codewords_group1': 12, 'blocks_group2': 5, 'data_codewords_group2': 13}},
        15: {'L': {'total_data_codewords': 523, 'ec_codewords_per_block': 22, 'blocks_group1': 5, 'data_codewords_group1': 87, 'blocks_group2': 1, 'data_codewords_group2': 88},
            'M': {'total_data_codewords': 415, 'ec_codewords_per_block': 24, 'blocks_group1': 5, 'data_codewords_group1': 41, 'blocks_group2': 5, 'data_codewords_group2': 42},
            'Q': {'total_data_codewords': 295, 'ec_codewords_per_block': 30, 'blocks_group1': 5, 'data_codewords_group1': 24, 'blocks_group2': 7, 'data_codewords_group2': 25},
            'H': {'total_data_codewords': 223, 'ec_codewords_per_block': 24, 'blocks_group1': 11, 'data_codewords_group1': 12, 'blocks_group2': 7, 'data_codewords_group2': 13}},
        16: {'L': {'total_data_codewords': 589, 'ec_codewords_per_block': 24, 'blocks_group1': 5, 'data_codewords_group1': 98, 'blocks_group2': 1, 'data_codewords_group2': 99},
            'M': {'total_data_codewords': 453, 'ec_codewords_per_block': 28, 'blocks_group1': 7, 'data_codewords_group1': 45, 'blocks_group2': 3, 'data_codewords_group2': 46},
            'Q': {'total_data_codewords': 325, 'ec_codewords_per_block': 24, 'blocks_group1': 15, 'data_codewords_group1': 19, 'blocks_group2': 2, 'data_codewords_group2': 20},
            'H': {'total_data_codewords': 253, 'ec_codewords_per_block': 30, 'blocks_group1': 3, 'data_codewords_group1': 15, 'blocks_group2': 13, 'data_codewords_group2': 16}},
        17: {'L': {'total_data_codewords': 647, 'ec_codewords_per_block': 28, 'blocks_group1': 1, 'data_codewords_group1': 107, 'blocks_group2': 5, 'data_codewords_group2': 108},
            'M': {'total_data_codewords': 507, 'ec_codewords_per_block': 28, 'blocks_group1': 10, 'data_codewords_group1': 46, 'blocks_group2': 1, 'data_codewords_group2': 47},
            'Q': {'total_data_codewords': 367, 'ec_codewords_per_block': 28, 'blocks_group1': 1, 'data_codewords_group1': 22, 'blocks_group2': 15, 'data_codewords_group2': 23},
            'H': {'total_data_codewords': 283, 'ec_codewords_per_block': 28, 'blocks_group1': 2, 'data_codewords_group1': 14, 'blocks_group2': 17, 'data_codewords_group2': 15}},
        18: {'L': {'total_data_codewords': 721, 'ec_codewords_per_block': 30, 'blocks_group1': 5, 'data_codewords_group1': 120, 'blocks_group2': 1, 'data_codewords_group2': 121},
            'M': {'total_data_codewords': 563, 'ec_codewords_per_block': 26, 'blocks_group1': 9, 'data_codewords_group1': 43, 'blocks_group2': 4, 'data_codewords_group2': 44},
            'Q': {'total_data_codewords': 397, 'ec_codewords_per_block': 28, 'blocks_group1': 17, 'data_codewords_group1': 22, 'blocks_group2': 1, 'data_codewords_group2': 23},
            'H': {'total_data_codewords': 313, 'ec_codewords_per_block': 28, 'blocks_group1': 2, 'data_codewords_group1': 14, 'blocks_group2': 19, 'data_codewords_group2': 15}},
        19: {'L': {'total_data_codewords': 795, 'ec_codewords_per_block': 28, 'blocks_group1': 3, 'data_codewords_group1': 113, 'blocks_group2': 4, 'data_codewords_group2': 114},
            'M': {'total_data_codewords': 627, 'ec_codewords_per_block': 26, 'blocks_group1': 3, 'data_codewords_group1': 44, 'blocks_group2': 11, 'data_codewords_group2': 45},
            'Q': {'total_data_codewords': 445, 'ec_codewords_per_block': 26, 'blocks_group1': 17, 'data_codewords_group1': 21, 'blocks_group2': 4, 'data_codewords_group2': 22},
            'H': {'total_data_codewords': 341, 'ec_codewords_per_block': 26, 'blocks_group1': 9, 'data_codewords_group1': 13, 'blocks_group2': 16, 'data_codewords_group2': 14}},
        20: {'L': {'total_data_codewords': 861, 'ec_codewords_per_block': 28, 'blocks_group1': 3, 'data_codewords_group1': 107, 'blocks_group2': 5, 'data_codewords_group2': 108},
            'M': {'total_data_codewords': 669, 'ec_codewords_per_block': 26, 'blocks_group1': 3, 'data_codewords_group1': 41, 'blocks_group2': 13, 'data_codewords_group2': 42},
            'Q': {'total_data_codewords': 485, 'ec_codewords_per_block': 30, 'blocks_group1': 15, 'data_codewords_group1': 24, 'blocks_group2': 5, 'data_codewords_group2': 25},
            'H': {'total_data_codewords': 385, 'ec_codewords_per_block': 28, 'blocks_group1': 15, 'data_codewords_group1': 15, 'blocks_group2': 10, 'data_codewords_group2': 16}},
        21: {'L': {'total_data_codewords': 932, 'ec_codewords_per_block': 28, 'blocks_group1': 4, 'data_codewords_group1': 116, 'blocks_group2': 4, 'data_codewords_group2': 117},
            'M': {'total_data_codewords': 714, 'ec_codewords_per_block': 26, 'blocks_group1': 17, 'data_codewords_group1': 42, 'blocks_group2': 0, 'data_codewords_group2': 0},
            'Q': {'total_data_codewords': 512, 'ec_codewords_per_block': 28, 'blocks_group1': 17, 'data_codewords_group1': 22, 'blocks_group2': 6, 'data_codewords_group2': 23},
            'H': {'total_data_codewords': 406, 'ec_codewords_per_block': 30, 'blocks_group1': 19, 'data_codewords_group1': 16, 'blocks_group2': 6, 'data_codewords_group2': 17}},
        22: {'L': {'total_data_codewords': 1006, 'ec_codewords_per_block': 28, 'blocks_group1': 2, 'data_codewords_group1': 111, 'blocks_group2': 7, 'data_codewords_group2': 112},
            'M': {'total_data_codewords': 782, 'ec_codewords_per_block': 28, 'blocks_group1': 17, 'data_codewords_group1': 46, 'blocks_group2': 0, 'data_codewords_group2': 0},
            'Q': {'total_data_codewords': 568, 'ec_codewords_per_block': 30, 'blocks_group1': 7, 'data_codewords_group1': 24, 'blocks_group2': 16, 'data_codewords_group2': 25},
            'H': {'total_data_codewords': 442, 'ec_codewords_per_block': 24, 'blocks_group1': 34, 'data_codewords_group1': 13, 'blocks_group2': 0, 'data_codewords_group2': 0}},
        23: {'L': {'total_data_codewords': 1094, 'ec_codewords_per_block': 30, 'blocks_group1': 4, 'data_codewords_group1': 121, 'blocks_group2': 5, 'data_codewords_group2': 122},
            'M': {'total_data_codewords': 860, 'ec_codewords_per_block': 28, 'blocks_group1': 4, 'data_codewords_group1': 47, 'blocks_group2': 14, 'data_codewords_group2': 48},
            'Q': {'total_data_codewords': 614, 'ec_codewords_per_block': 30, 'blocks_group1': 11, 'data_codewords_group1': 24, 'blocks_group2': 14, 'data_codewords_group2': 25},
            'H': {'total_data_codewords': 464, 'ec_codewords_per_block': 30, 'blocks_group1': 16, 'data_codewords_group1': 15, 'blocks_group2': 14, 'data_codewords_group2': 16}},
        24: {'L': {'total_data_codewords': 1174, 'ec_codewords_per_block': 30, 'blocks_group1': 6, 'data_codewords_group1': 117, 'blocks_group2': 4, 'data_codewords_group2': 118},
            'M': {'total_data_codewords': 914, 'ec_codewords_per_block': 28, 'blocks_group1': 6, 'data_codewords_group1': 45, 'blocks_group2': 14, 'data_codewords_group2': 46},
            'Q': {'total_data_codewords': 664, 'ec_codewords_per_block': 30, 'blocks_group1': 11, 'data_codewords_group1': 24, 'blocks_group2': 16, 'data_codewords_group2': 25},
            'H': {'total_data_codewords': 514, 'ec_codewords_per_block': 30, 'blocks_group1': 30, 'data_codewords_group1': 16, 'blocks_group2': 2, 'data_codewords_group2': 17}},
        25: {'L': {'total_data_codewords': 1276, 'ec_codewords_per_block': 26, 'blocks_group1': 8, 'data_codewords_group1': 106, 'blocks_group2': 4, 'data_codewords_group2': 107},
            'M': {'total_data_codewords': 1000, 'ec_codewords_per_block': 28, 'blocks_group1': 8, 'data_codewords_group1': 47, 'blocks_group2': 13, 'data_codewords_group2': 48},
            'Q': {'total_data_codewords': 718, 'ec_codewords_per_block': 30, 'blocks_group1': 7, 'data_codewords_group1': 24, 'blocks_group2': 22, 'data_codewords_group2': 25},
            'H': {'total_data_codewords': 538, 'ec_codewords_per_block': 30, 'blocks_group1': 22, 'data_codewords_group1': 15, 'blocks_group2': 13, 'data_codewords_group2': 16}},
        26: {'L': {'total_data_codewords': 1370, 'ec_codewords_per_block': 28, 'blocks_group1': 10, 'data_codewords_group1': 114, 'blocks_group2': 2, 'data_codewords_group2': 115},
            'M': {'total_data_codewords': 1062, 'ec_codewords_per_block': 28, 'blocks_group1': 19, 'data_codewords_group1': 46, 'blocks_group2': 4, 'data_codewords_group2': 47},
            'Q': {'total_data_codewords': 754, 'ec_codewords_per_block': 28, 'blocks_group1': 28, 'data_codewords_group1': 22, 'blocks_group2': 6, 'data_codewords_group2': 23},
            'H': {'total_data_codewords': 596, 'ec_codewords_per_block': 30, 'blocks_group1': 33, 'data_codewords_group1': 16, 'blocks_group2': 4, 'data_codewords_group2': 17}},
        27: {'L': {'total_data_codewords': 1468, 'ec_codewords_per_block': 30, 'blocks_group1': 8, 'data_codewords_group1': 122, 'blocks_group2': 4, 'data_codewords_group2': 123},
            'M': {'total_data_codewords': 1128, 'ec_codewords_per_block': 28, 'blocks_group1': 22, 'data_codewords_group1': 45, 'blocks_group2': 3, 'data_codewords_group2': 46},
            'Q': {'total_data_codewords': 808, 'ec_codewords_per_block': 30, 'blocks_group1': 8, 'data_codewords_group1': 23, 'blocks_group2': 26, 'data_codewords_group2': 24},
            'H': {'total_data_codewords': 628, 'ec_codewords_per_block': 30, 'blocks_group1': 12, 'data_codewords_group1': 15, 'blocks_group2': 28, 'data_codewords_group2': 16}},
        28: {'L': {'total_data_codewords': 1531, 'ec_codewords_per_block': 30, 'blocks_group1': 3, 'data_codewords_group1': 117, 'blocks_group2': 10, 'data_codewords_group2': 118},
            'M': {'total_data_codewords': 1193, 'ec_codewords_per_block': 28, 'blocks_group1': 3, 'data_codewords_group1': 45, 'blocks_group2': 23, 'data_codewords_group2': 46},
            'Q': {'total_data_codewords': 871, 'ec_codewords_per_block': 30, 'blocks_group1': 4, 'data_codewords_group1': 24, 'blocks_group2': 31, 'data_codewords_group2': 25},
            'H': {'total_data_codewords': 661, 'ec_codewords_per_block': 30, 'blocks_group1': 11, 'data_codewords_group1': 15, 'blocks_group2': 31, 'data_codewords_group2': 16}},
        29: {'L': {'total_data_codewords': 1631, 'ec_codewords_per_block': 30, 'blocks_group1': 7, 'data_codewords_group1': 116, 'blocks_group2': 7, 'data_codewords_group2': 117},
            'M': {'total_data_codewords': 1267, 'ec_codewords_per_block': 28, 'blocks_group1': 21, 'data_codewords_group1': 45, 'blocks_group2': 7, 'data_codewords_group2': 46},
            'Q': {'total_data_codewords': 911, 'ec_codewords_per_block': 30, 'blocks_group1': 1, 'data_codewords_group1': 23, 'blocks_group2': 37, 'data_codewords_group2': 24},
            'H': {'total_data_codewords': 701, 'ec_codewords_per_block': 30, 'blocks_group1': 19, 'data_codewords_group1': 15, 'blocks_group2': 26, 'data_codewords_group2': 16}},
        30: {'L': {'total_data_codewords': 1735, 'ec_codewords_per_block': 30, 'blocks_group1': 5, 'data_codewords_group1': 115, 'blocks_group2': 10, 'data_codewords_group2': 116},
            'M': {'total_data_codewords': 1373, 'ec_codewords_per_block': 28, 'blocks_group1': 19, 'data_codewords_group1': 47, 'blocks_group2': 10, 'data_codewords_group2': 48},
            'Q': {'total_data_codewords': 985, 'ec_codewords_per_block': 30, 'blocks_group1': 15, 'data_codewords_group1': 24, 'blocks_group2': 25, 'data_codewords_group2': 25},
            'H': {'total_data_codewords': 745, 'ec_codewords_per_block': 30, 'blocks_group1': 23, 'data_codewords_group1': 15, 'blocks_group2': 25, 'data_codewords_group2': 16}},
        31: {'L': {'total_data_codewords': 1843, 'ec_codewords_per_block': 30, 'blocks_group1': 13, 'data_codewords_group1': 115, 'blocks_group2': 3, 'data_codewords_group2': 116},
            'M': {'total_data_codewords': 1455, 'ec_codewords_per_block': 28, 'blocks_group1': 2, 'data_codewords_group1': 46, 'blocks_group2': 29, 'data_codewords_group2': 47},
            'Q': {'total_data_codewords': 1033, 'ec_codewords_per_block': 30, 'blocks_group1': 42, 'data_codewords_group1': 24, 'blocks_group2': 1, 'data_codewords_group2': 25},
            'H': {'total_data_codewords': 793, 'ec_codewords_per_block': 30, 'blocks_group1': 23, 'data_codewords_group1': 15, 'blocks_group2': 28, 'data_codewords_group2': 16}},
        32: {'L': {'total_data_codewords': 1955, 'ec_codewords_per_block': 30, 'blocks_group1': 17, 'data_codewords_group1': 115, 'blocks_group2': 0, 'data_codewords_group2': 0},
            'M': {'total_data_codewords': 1541, 'ec_codewords_per_block': 28, 'blocks_group1': 10, 'data_codewords_group1': 46, 'blocks_group2': 23, 'data_codewords_group2': 47},
            'Q': {'total_data_codewords': 1115, 'ec_codewords_per_block': 30, 'blocks_group1': 10, 'data_codewords_group1': 24, 'blocks_group2': 35, 'data_codewords_group2': 25},
            'H': {'total_data_codewords': 845, 'ec_codewords_per_block': 30, 'blocks_group1': 19, 'data_codewords_group1': 15, 'blocks_group2': 35, 'data_codewords_group2': 16}},
        33: {'L': {'total_data_codewords': 2071, 'ec_codewords_per_block': 30, 'blocks_group1': 17, 'data_codewords_group1': 115, 'blocks_group2': 1, 'data_codewords_group2': 116},
            'M': {'total_data_codewords': 1631, 'ec_codewords_per_block': 28, 'blocks_group1': 14, 'data_codewords_group1': 46, 'blocks_group2': 21, 'data_codewords_group2': 47},
            'Q': {'total_data_codewords': 1171, 'ec_codewords_per_block': 30, 'blocks_group1': 29, 'data_codewords_group1': 24, 'blocks_group2': 19, 'data_codewords_group2': 25},
            'H': {'total_data_codewords': 901, 'ec_codewords_per_block': 30, 'blocks_group1': 11, 'data_codewords_group1': 15, 'blocks_group2': 46, 'data_codewords_group2': 16}},
        34: {'L': {'total_data_codewords': 2191, 'ec_codewords_per_block': 30, 'blocks_group1': 13, 'data_codewords_group1': 115, 'blocks_group2': 6, 'data_codewords_group2': 116},
            'M': {'total_data_codewords': 1725, 'ec_codewords_per_block': 28, 'blocks_group1': 14, 'data_codewords_group1': 46, 'blocks_group2': 23, 'data_codewords_group2': 47},
            'Q': {'total_data_codewords': 1231, 'ec_codewords_per_block': 30, 'blocks_group1': 44, 'data_codewords_group1': 24, 'blocks_group2': 7, 'data_codewords_group2': 25},
            'H': {'total_data_codewords': 961, 'ec_codewords_per_block': 30, 'blocks_group1': 59, 'data_codewords_group1': 16, 'blocks_group2': 1, 'data_codewords_group2': 17}},
        35: {'L': {'total_data_codewords': 2306, 'ec_codewords_per_block': 30, 'blocks_group1': 12, 'data_codewords_group1': 121, 'blocks_group2': 7, 'data_codewords_group2': 122},
            'M': {'total_data_codewords': 1812, 'ec_codewords_per_block': 28, 'blocks_group1': 12, 'data_codewords_group1': 47, 'blocks_group2': 26, 'data_codewords_group2': 48},
            'Q': {'total_data_codewords': 1286, 'ec_codewords_per_block': 30, 'blocks_group1': 39, 'data_codewords_group1': 24, 'blocks_group2': 14, 'data_codewords_group2': 25},
            'H': {'total_data_codewords': 986, 'ec_codewords_per_block': 30, 'blocks_group1': 22, 'data_codewords_group1': 15, 'blocks_group2': 41, 'data_codewords_group2': 16}},
        36: {'L': {'total_data_codewords': 2434, 'ec_codewords_per_block': 30, 'blocks_group1': 6, 'data_codewords_group1': 121, 'blocks_group2': 14, 'data_codewords_group2': 122},
            'M': {'total_data_codewords': 1914, 'ec_codewords_per_block': 28, 'blocks_group1': 6, 'data_codewords_group1': 47, 'blocks_group2': 34, 'data_codewords_group2': 48},
            'Q': {'total_data_codewords': 1354, 'ec_codewords_per_block': 30, 'blocks_group1': 46, 'data_codewords_group1': 24, 'blocks_group2': 10, 'data_codewords_group2': 25},
            'H': {'total_data_codewords': 1054, 'ec_codewords_per_block': 30, 'blocks_group1': 2, 'data_codewords_group1': 15, 'blocks_group2': 64, 'data_codewords_group2': 16}},
        37: {'L': {'total_data_codewords': 2566, 'ec_codewords_per_block': 30, 'blocks_group1': 17, 'data_codewords_group1': 122, 'blocks_group2': 4, 'data_codewords_group2': 123},
            'M': {'total_data_codewords': 1992, 'ec_codewords_per_block': 28, 'blocks_group1': 29, 'data_codewords_group1': 46, 'blocks_group2': 14, 'data_codewords_group2': 47},
            'Q': {'total_data_codewords': 1426, 'ec_codewords_per_block': 30, 'blocks_group1': 49, 'data_codewords_group1': 24, 'blocks_group2': 10, 'data_codewords_group2': 25},
            'H': {'total_data_codewords': 1096, 'ec_codewords_per_block': 30, 'blocks_group1': 24, 'data_codewords_group1': 15, 'blocks_group2': 46, 'data_codewords_group2': 16}},
        38: {'L': {'total_data_codewords': 2702, 'ec_codewords_per_block': 30, 'blocks_group1': 4, 'data_codewords_group1': 122, 'blocks_group2': 18, 'data_codewords_group2': 123},
            'M': {'total_data_codewords': 2102, 'ec_codewords_per_block': 28, 'blocks_group1': 13, 'data_codewords_group1': 46, 'blocks_group2': 32, 'data_codewords_group2': 47},
            'Q': {'total_data_codewords': 1502, 'ec_codewords_per_block': 30, 'blocks_group1': 48, 'data_codewords_group1': 24, 'blocks_group2': 14, 'data_codewords_group2': 25},
            'H': {'total_data_codewords': 1142, 'ec_codewords_per_block': 30, 'blocks_group1': 42, 'data_codewords_group1': 15, 'blocks_group2': 32, 'data_codewords_group2': 16}},
        39: {'L': {'total_data_codewords': 2812, 'ec_codewords_per_block': 30, 'blocks_group1': 20, 'data_codewords_group1': 117, 'blocks_group2': 4, 'data_codewords_group2': 118},
            'M': {'total_data_codewords': 2216, 'ec_codewords_per_block': 28, 'blocks_group1': 40, 'data_codewords_group1': 47, 'blocks_group2': 7, 'data_codewords_group2': 48},
            'Q': {'total_data_codewords': 1582, 'ec_codewords_per_block': 30, 'blocks_group1': 43, 'data_codewords_group1': 24, 'blocks_group2': 22, 'data_codewords_group2': 25},
            'H': {'total_data_codewords': 1222, 'ec_codewords_per_block': 30, 'blocks_group1': 10, 'data_codewords_group1': 15, 'blocks_group2': 67, 'data_codewords_group2': 16}},
        40: {'L': {'total_data_codewords': 2956, 'ec_codewords_per_block': 30, 'blocks_group1': 19, 'data_codewords_group1': 118, 'blocks_group2': 6, 'data_codewords_group2': 119},
            'M': {'total_data_codewords': 2334, 'ec_codewords_per_block': 28, 'blocks_group1': 18, 'data_codewords_group1': 47, 'blocks_group2': 31, 'data_codewords_group2': 48},
            'Q': {'total_data_codewords': 1666, 'ec_codewords_per_block': 30, 'blocks_group1': 34, 'data_codewords_group1': 24, 'blocks_group2': 34, 'data_codewords_group2': 25},
            'H': {'total_data_codewords': 1276, 'ec_codewords_per_block': 30, 'blocks_group1': 20, 'data_codewords_group1': 15, 'blocks_group2': 61, 'data_codewords_group2': 16}}
    }

    # Number of remainder bits for each QR code version for building the final bit stream
    QR_REMAINDER_BITS = {
        1: 0,
        2: 7,
        3: 7,
        4: 7,
        5: 7,
        6: 7,
        7: 0,
        8: 0,
        9: 0,
        10: 0,
        11: 0,
        12: 0,
        13: 0,
        14: 3,
        15: 3,
        16: 3,
        17: 3,
        18: 3,
        19: 3,
        20: 3,
        21: 4,
        22: 4,
        23: 4,
        24: 4,
        25: 4,
        26: 4,
        27: 4,
        28: 3,
        29: 3,
        30: 3,
        31: 3,
        32: 3,
        33: 3,
        34: 3,
        35: 0,
        36: 0,
        37: 0,
        38: 0,
        39: 0,
        40: 0
    }

    # Number of bits used to encode the character count for each encoding mode and QR code version range
    CHARACTER_COUNT_BITS = {
        (1, 9): {
            "numeric": 10,
            "alphanumeric": 9,
            "byte": 8,
            "kanji": 8,
        },
        (10, 26): {
            "numeric": 12,
            "alphanumeric": 11,
            "byte": 16,
            "kanji": 10,
        },
        (27, 40): {
            "numeric": 14,
            "alphanumeric": 13,
            "byte": 16,
            "kanji": 12,
        },
    }

    ALPHANUMERIC_TABLE = {"0": 0, "1": 1, "2": 2, "3": 3, "4": 4, "5": 5, "6": 6, "7": 7, "8": 8, "9": 9,
                        "A": 10, "B": 11, "C": 12, "D": 13, "E": 14, "F": 15, "G": 16, "H": 17, "I": 18, "J": 19,
                        "K": 20, "L": 21, "M": 22, "N": 23, "O": 24, "P": 25, "Q": 26, "R": 27, "S": 28, "T": 29, "U": 30, "V": 31,
                        "W": 32, "X": 33, "Y": 34, "Z": 35, " ": 36, "$": 37, "%": 38, "*": 39, "+": 40, "-": 41, ".": 42, "/": 43, ":": 44}

    # Reads from left to right
    encoded_data = None

    # Get user input for the data to encode in the QR code and determine its length
    if input_data is None or input_data.strip() == "":
        raise ValueError("Input data cannot be None or empty. Please provide valid input data to encode in the QR code.")

    # Choose the encoding mode based on the input data
    encoding_mode = select_encoding_mode(input_data)

    error_correction_level = error_correction_level.upper()

    if error_correction_level not in ['L', 'M', 'Q', 'H']:
        print(f"Error correction level {error_correction_level} is invalid. Defaulting to 'L'.")
        error_correction_level = 'L'

    # Determine the length of the input data based on the selected encoding mode
    input_data_length = None

    # If using byte mode, the character count is based on the number of bytes in UTF-8 encoding, not the number of characters
    if encoding_mode == 'byte':
        try:
            input_data_length = len(input_data.encode('iso-8859-1'))
        except UnicodeEncodeError:
            input_data_length = len(input_data.encode('utf-8'))
    else:
        input_data_length = len(input_data)

    # If input data length exceeds the maximum capacity for the largest QR code version with the selected encoding mode and error correction level, cut the input data to fit
    max_capacity = QR_CAPACITIES[40][error_correction_level][encoding_mode]
    if input_data_length > max_capacity:
        print(f"Input data length exceeds the maximum capacity for QR code version 40 with error correction level {error_correction_level}. Cutting data to fit.")
        input_data = input_data[:max_capacity]
        
        # If using byte mode, the character count is based on the number of bytes in UTF-8 encoding, not the number of characters
        if encoding_mode == 'byte':
            try:
                input_data_length = len(input_data.encode('iso-8859-1'))
            except UnicodeEncodeError:
                input_data_length = len(input_data.encode('utf-8'))
        else:
            input_data_length = len(input_data)


    # Determine the minimum QR code version that can accommodate the input data or use the specified version if provided
    if qr_code_version is None:
        qr_code_version = select_qr_code_version(input_data_length, encoding_mode, error_correction_level, QR_CAPACITIES)
    else:
        if qr_code_version < 1 or qr_code_version > 40:
            print(f"QR code version {qr_code_version} is invalid. Defaulting to minimum valid version.")
            qr_code_version = select_qr_code_version(input_data_length, encoding_mode, error_correction_level, QR_CAPACITIES)

        if input_data_length > QR_CAPACITIES[qr_code_version][error_correction_level][encoding_mode]:
            print(f"Input data length exceeds the maximum capacity for QR code version {qr_code_version} with error correction level {error_correction_level}. Cutting data to fit.")
            input_data = input_data[:QR_CAPACITIES[qr_code_version][error_correction_level][encoding_mode]]
            input_data_length = len(input_data)

    # Start encoded data with the mode indicator bits
    encoded_data = ENCODING_MODE_INDICATORS[encoding_mode]

    # Add character count indicator bits 
    encoded_data += format(input_data_length, f'0{get_character_count_bit_length(qr_code_version, encoding_mode, CHARACTER_COUNT_BITS)}b')

    # Add encoded original data bits
    encoded_data += encode_data(input_data, encoding_mode, ALPHANUMERIC_TABLE)

    # Add padding bits (terminator, zero padding, and pad codewords) to fit the QR code capacity
    encoded_data += add_padding_bits(encoded_data, qr_code_version, error_correction_level, QR_ERROR_CORRECTION_TABLE)

    # Generate error correction codewords for the encoded data
    data_codewords, error_correction_codewords = generate_error_correction_codewords(encoded_data, qr_code_version, error_correction_level, QR_ERROR_CORRECTION_TABLE)

    # Combine the encoded data and error correction codewords to form the final bit stream for the QR code
    final_bit_stream = create_final_bit_stream(data_codewords, error_correction_codewords, qr_code_version, QR_REMAINDER_BITS)

    print(f"QR code version selected: {qr_code_version}")
    print(f"Error correction level selected: {error_correction_level}")
    print(f"Encoding mode selected: {encoding_mode}")
    print(f"Input data length: {input_data_length}")
    print(f"Maximum capacity for selected version and error correction level: {QR_CAPACITIES[qr_code_version][error_correction_level][encoding_mode]}")

    return QRCodeData(
        version=qr_code_version,
        error_correction_level=error_correction_level,
        encoding_mode=encoding_mode,
        final_bit_stream=final_bit_stream
    )


def add_finder_patterns(qr_matrix, is_data_matrix):
    # Add finder patterns to the QR code matrix
    # Finder patterns are located at the top-left, top-right, and bottom-left corners of the QR code
    finder_pattern = [
        [1, 1, 1, 1, 1, 1, 1],
        [1, 0, 0, 0, 0, 0, 1],
        [1, 0, 1, 1, 1, 0, 1],
        [1, 0, 1, 1, 1, 0, 1],
        [1, 0, 1, 1, 1, 0, 1],
        [1, 0, 0, 0, 0, 0, 1],
        [1, 1, 1, 1, 1, 1, 1]
    ]

    # Top-left finder pattern
    for i in range(7):
        for j in range(7):
            qr_matrix[i][j] = finder_pattern[i][j]
            is_data_matrix[i][j] = False  # Mark finder pattern area as non-data

    # Top-right finder pattern
    for i in range(7):
        for j in range(7):
            qr_matrix[i][len(qr_matrix) - j - 1] = finder_pattern[i][j]
            is_data_matrix[i][len(is_data_matrix) - j - 1] = False  # Mark finder pattern area as non-data

    # Bottom-left finder pattern
    for i in range(7):
        for j in range(7):
            qr_matrix[len(qr_matrix) - i - 1][j] = finder_pattern[i][j]
            is_data_matrix[len(is_data_matrix) - i - 1][j] = False  # Mark finder pattern area as non-data


def add_separator_patterns(qr_matrix, is_data_matrix):
    # Add separator patterns (white space) around the finder patterns
    for i in range(8):
        qr_matrix[i][7] = 0  # Right of top-left finder pattern
        qr_matrix[7][i] = 0  # Below top-left finder pattern
        qr_matrix[i][len(qr_matrix) - 8] = 0  # Left of top-right finder pattern
        qr_matrix[7][len(qr_matrix) - i - 1] = 0  # Below top-right finder pattern
        qr_matrix[len(qr_matrix) - i - 1][7] = 0  # Right of bottom-left finder pattern
        qr_matrix[len(qr_matrix) - 8][i] = 0  # Above bottom-left finder pattern

        is_data_matrix[i][7] = False
        is_data_matrix[7][i] = False
        is_data_matrix[i][len(is_data_matrix) - 8] = False
        is_data_matrix[7][len(is_data_matrix) - i - 1] = False
        is_data_matrix[len(is_data_matrix) - i - 1][7] = False
        is_data_matrix[len(is_data_matrix) - 8][i] = False


def add_alignment_patterns(qr_matrix, is_data_matrix, version):
    # Add alignment patterns to the QR code matrix based on the version
    allignment_pattern = [
        [1, 1, 1, 1, 1],
        [1, 0, 0, 0, 1],
        [1, 0, 1, 0, 1],
        [1, 0, 0, 0, 1],
        [1, 1, 1, 1, 1]
    ]

    allignment_pattern_locations = {
        1: [],
        2: [6, 18],
        3: [6, 22],
        4: [6, 26],
        5: [6, 30],
        6: [6, 34],
        7: [6, 22, 38],
        8: [6, 24, 42],
        9: [6, 26, 46],
        10: [6, 28, 50],
        11: [6, 30, 54],
        12: [6, 32, 58],
        13: [6, 34, 62],
        14: [6, 26, 46, 66],
        15: [6, 26, 48, 70],
        16: [6, 26, 50, 74],
        17: [6, 30, 54, 78],
        18: [6, 30, 56, 82],
        19: [6, 30, 58, 86],
        20: [6, 34, 62, 90],
        21: [6, 28, 50, 72, 94],
        22: [6, 26, 50, 74, 98],
        23: [6, 30, 54, 78, 102],
        24: [6, 28, 54, 80, 106],
        25: [6, 32, 58, 84, 110],
        26: [6, 30, 58, 86, 114],
        27: [6, 34, 62, 90, 118],
        28: [6, 26, 50, 74, 98, 122],
        29: [6, 30, 54, 78, 102, 126],
        30:	[6, 26, 52, 78, 104, 130],
        31:	[6, 30, 56, 82, 108, 134],
        32:	[6, 34, 60, 86, 112, 138],
        33:	[6, 30, 58, 86, 114, 142],
        34:	[6, 34, 62, 90, 118, 146],
        35:	[6, 30, 54, 78, 102, 126, 150],
        36:	[6, 24, 50, 76, 102, 128, 154],
        37:	[6, 28, 54, 80, 106, 132, 158],
        38:	[6, 32, 58, 84, 110, 136, 162],
        39:	[6, 26, 54, 82, 110, 138, 166],
        40:	[6, 30, 58, 86, 114, 142, 170]
    }

    # Add alignment patterns to the QR code matrix based on the version
    locations = allignment_pattern_locations[version]
    for row in range(len(locations)):
        for column in range(len(locations)):
            if (row == 0 and column == 0) or (row == 0 and column == len(locations) - 1) or (row == len(locations) - 1 and column == 0):
                continue  # Skip the corners where finder patterns are located
            else:
                matrix_row = locations[row]
                matrix_col = locations[column]
                for k in range(5):
                    for l in range(5):
                        qr_matrix[matrix_row - 2 + k][matrix_col - 2 + l] = allignment_pattern[k][l]
                        is_data_matrix[matrix_row - 2 + k][matrix_col - 2 + l] = False


def add_timing_patterns(qr_matrix, is_data_matrix):
    # Add timing patterns to the QR code matrix
    for i in range(8, len(qr_matrix) - 8):
        qr_matrix[6][i] = 1 if i % 2 == 0 else 0  # Horizontal timing pattern
        qr_matrix[i][6] = 1 if i % 2 == 0 else 0  # Vertical timing pattern
        is_data_matrix[6][i] = False
        is_data_matrix[i][6] = False


def add_dark_module(qr_matrix, is_data_matrix):
    # Add dark module (black square) at the bottom-left corner of the QR code matrix
    qr_matrix[len(qr_matrix) - 8][8] = 1  # Dark module is located at (4 * version + 9, 8) in the QR code matrix
    is_data_matrix[len(is_data_matrix) - 8][8] = False


def reserve_format_and_version_info(qr_matrix, is_data_matrix, version):
    # Reserve space for format information and version information in the QR code matrix
    # Format information is located in the areas adjacent to the finder patterns
    # Version information is located in the areas adjacent to the timing patterns for versions 7 and above

    # Reserve space for format information
    for i in range(6):
        qr_matrix[8][i] = 3  # Top-left format information area
        qr_matrix[i][8] = 3  # Top-left format information area
        is_data_matrix[8][i] = False
        is_data_matrix[i][8] = False

    for i in range(7):
        qr_matrix[len(qr_matrix) - i - 1][8] = 3  # Bottom-left format information area
        is_data_matrix[len(is_data_matrix) - i - 1][8] = False

    for i in range(8):
        qr_matrix[8][len(qr_matrix) - i - 1] = 3  # Top-right format information area
        is_data_matrix[8][len(is_data_matrix) - i - 1] = False

    qr_matrix[8][7] = 3 # Top-left format information area
    qr_matrix[8][8] = 3 # Top-left format information area
    qr_matrix[7][8] = 3 # Top-left format information area
    is_data_matrix[8][7] = False
    is_data_matrix[8][8] = False
    is_data_matrix[7][8] = False

    if version >= 7:
        # Reserve space for version information
        for i in range(6):
            for j in range(3):
                qr_matrix[i][len(qr_matrix) - j - 9] = 3  # Top-right version information area
                is_data_matrix[i][len(is_data_matrix) - j - 9] = False
                qr_matrix[len(qr_matrix) - j - 9][i] = 3  # Bottom-left version information area
                is_data_matrix[len(is_data_matrix) - j - 9][i] = False


def add_format_and_version_info(qr_matrix, is_data_matrix, version, error_correction_level, mask_pattern):
    # Add format information and version information to the QR code matrix
    
    list_of_format_strings = {
        ('L', 0): '111011111000100',
        ('L', 1): '111001011110011',
        ('L', 2): '111110110101010',
        ('L', 3): '111100010011101',
        ('L', 4): '110011000101111',
        ('L', 5): '110001100011000',
        ('L', 6): '110110001000001',
        ('L', 7): '110100101110110',
        ('M', 0): '101010000010010',
        ('M', 1): '101000100100101',
        ('M', 2): '101111001111100',
        ('M', 3): '101101101001011',
        ('M', 4): '100010111111001',
        ('M', 5): '100000011001110',
        ('M', 6): '100111110010111',
        ('M', 7): '100101010100000',
        ('Q', 0): '011010101011111',
        ('Q', 1): '011000001101000',
        ('Q', 2): '011111100110001',
        ('Q', 3): '011101000000110',
        ('Q', 4): '010010010110100',
        ('Q', 5): '010000110000011',
        ('Q', 6): '010111011011010',
        ('Q', 7): '010101111101101',
        ('H', 0): '001011010001001',
        ('H', 1): '001001110111110',
        ('H', 2): '001110011100111',
        ('H', 3): '001100111010000',
        ('H', 4): '000011101100010',
        ('H', 5): '000001001010101',
        ('H', 6): '000110100001100',
        ('H', 7): '000100000111011'
    }

    list_of_version_strings = {
        '7':	'000111110010010100',
        '8':	'001000010110111100',
        '9':	'001001101010011001',
        '10':	'001010010011010011',
        '11':	'001011101111110110',
        '12':	'001100011101100010',
        '13':	'001101100001000111',
        '14':	'001110011000001101',
        '15':	'001111100100101000',
        '16':	'010000101101111000',
        '17':	'010001010001011101',
        '18':	'010010101000010111',
        '19':	'010011010100110010',
        '20':	'010100100110100110',
        '21':	'010101011010000011',
        '22':	'010110100011001001',
        '23':	'010111011111101100',
        '24':	'011000111011000100',
        '25':	'011001000111100001',
        '26':	'011010111110101011',
        '27':	'011011000010001110',
        '28':	'011100110000011010',
        '29':	'011101001100111111',
        '30':	'011110110101110101',
        '31':	'011111001001010000',
        '32':	'100000100111010101',
        '33':	'100001011011110000',
        '34':	'100010100010111010',
        '35':	'100011011110011111',
        '36':	'100100101100001011',
        '37':	'100101010000101110',
        '38':	'100110101001100100',
        '39':	'100111010101000001',
        '40':	'101000110001101001'
    }

    format_string = list_of_format_strings[(error_correction_level, mask_pattern)]
    version_string = list_of_version_strings[str(version)] if version >= 7 else None

    # Add format information to the QR code matrix
    for i in range(15):
        bit = int(format_string[i])

        # 0-5
        if i < 6:
            qr_matrix[8][i] = bit
            qr_matrix[len(qr_matrix) - 1 - i][8] = bit
        # 6
        elif i == 6:
            qr_matrix[8][7] = bit
            qr_matrix[len(qr_matrix) - 1 - i][8] = bit
        # 7
        elif i == 7:
            qr_matrix[8][8] = bit
            qr_matrix[8][len(qr_matrix) - 15 + i] = bit
        # 8
        elif i == 8:
            qr_matrix[7][8] = bit
            qr_matrix[8][len(qr_matrix) - 15 + i] = bit
        # 9-14
        else:
            qr_matrix[14-i][8] = bit
            qr_matrix[8][len(qr_matrix) - 15 + i] = bit

    # Add version information to the QR code matrix for versions 7 and above
    if version >= 7:
        for i in range(18):
            bit = int(version_string[17 - i])  # <-- reversed order

            qr_matrix[i // 3][len(qr_matrix) - 11 + (i % 3)] = bit
            qr_matrix[len(qr_matrix) - 11 + (i % 3)][i // 3] = bit


def add_data_bits(qr_matrix, final_bit_stream):
    bit_index = 0
    direction = -1
    size = len(qr_matrix)

    for col in range(size - 1, 0, -2):
        current_col = col if col > 6 else col - 1

        row_range = (
            range(size - 1, -1, -1)
            if direction == -1
            else range(size)
        )

        for row in row_range:
            for i in range(2):
                c = current_col - i

                if qr_matrix[row][c] == 2:
                    if bit_index < len(final_bit_stream):
                        qr_matrix[row][c] = int(final_bit_stream[bit_index])
                        bit_index += 1
                    else:
                        return

        direction *= -1


def calculate_penalty_score(qr_matrix):
    penalty_score = 0

    # Rule 1: Adjacent modules in row/column in same color
    for row in qr_matrix:
        count = 1
        for i in range(1, len(row)):
            if row[i] == row[i - 1]:
                count += 1
            else:
                if count >= 5:
                    penalty_score += 3 + (count - 5)
                count = 1
        if count >= 5:
            penalty_score += 3 + (count - 5)

    for col in range(len(qr_matrix[0])):
        count = 1
        for i in range(1, len(qr_matrix)):
            if qr_matrix[i][col] == qr_matrix[i - 1][col]:
                count += 1
            else:
                if count >= 5:
                    penalty_score += 3 + (count - 5)
                count = 1
        if count >= 5:
            penalty_score += 3 + (count - 5)

    # Rule 2: Blocks of modules in same color
    for row in range(len(qr_matrix) - 1):
        for col in range(len(qr_matrix[0]) - 1):
            if (
                qr_matrix[row][col] == qr_matrix[row][col + 1]
                and qr_matrix[row][col] == qr_matrix[row + 1][col]
                and qr_matrix[row][col] == qr_matrix[row + 1][col + 1]
            ):
                penalty_score += 3

    # Rule 3: Patterns similar to the finder patterns
    finder_pattern = [1, 0, 1, 1, 1, 0, 1]
    for row in qr_matrix:
        for i in range(len(row) - len(finder_pattern) + 1):
            if row[i:i + len(finder_pattern)] == finder_pattern:
                penalty_score += 40

    for col in range(len(qr_matrix[0])):
        for i in range(len(qr_matrix) - len(finder_pattern) + 1):
            if [qr_matrix[j][col] for j in range(i, i + len(finder_pattern))] == finder_pattern:
                penalty_score += 40

    # Rule 4: Proportion of dark modules
    total_modules = len(qr_matrix) * len(qr_matrix[0])
    dark_modules = sum(
        1 for row in qr_matrix for m in row if m == 1
    )

    percent = (dark_modules / total_modules) * 100

    # Find nearest multiples of 5
    lower = (percent // 5) * 5
    upper = lower + 5

    penalty_score += min(abs(lower - 50) // 5, abs(upper - 50) // 5) * 10

    return penalty_score


def mask_data_bits(qr_matrix: list, is_data_matrix: list, mask_pattern: int = None):
    # Mask patterns
    mask_patterns = [
        lambda row, column: (row + column) % 2 == 0,
        lambda row, column: row % 2 == 0,
        lambda row, column: column % 3 == 0,
        lambda row, column: (row + column) % 3 == 0,
        lambda row, column: (row // 2 + column // 3) % 2 == 0,
        lambda row, column: (row * column) % 2 + (row * column) % 3 == 0,
        lambda row, column: ((row * column) % 2 + (row * column) % 3) % 2 == 0,
        lambda row, column: ((row + column) % 2 + (row * column) % 3) % 2 == 0,
    ]

    if mask_pattern is not None and (mask_pattern < 0 or mask_pattern > 7):
        print(f"Mask pattern {mask_pattern} is invalid (must be between 0 and 7). Defaulting to automatic selection.")
        mask_pattern = None

    # If a specific mask pattern is provided, apply it directly to the data bits in the QR code matrix. 
    # Otherwise, apply all mask patterns to the data bits and calculate the penalty score for each pattern to select the best one.
    if mask_pattern is not None:
        for row in range(len(qr_matrix)):
            for column in range(len(qr_matrix[row])):
                if is_data_matrix[row][column]:
                    if mask_patterns[mask_pattern](row, column):
                        qr_matrix[row][column] ^= 1  # Apply the chosen mask pattern

        print(f"Selected mask pattern: {mask_pattern}")
        return mask_pattern
    else:
        # Penalty scores for each mask pattern
        penalty_scores = [0] * 8

        # Apply each mask pattern to the data bits in the QR code matrix and calculate the penalty score for each pattern
        for mask_index, mask_pattern in enumerate(mask_patterns):
            for row in range(len(qr_matrix)):
                for column in range(len(qr_matrix[row])):
                    if is_data_matrix[row][column]:
                        if mask_pattern(row, column):
                            qr_matrix[row][column] ^= 1  # Invert the data bit

            # Calculate the penalty score for the current mask pattern
            penalty_scores[mask_index] = calculate_penalty_score(qr_matrix)

            # Revert the changes made by the current mask pattern to restore the original data bits
            for row in range(len(qr_matrix)):
                for column in range(len(qr_matrix[row])):
                    if is_data_matrix[row][column]:
                        if mask_pattern(row, column):
                            qr_matrix[row][column] ^= 1  # Revert the data bit

        # Select the mask pattern with the lowest penalty score and apply it to the data bits in the QR code matrix
        best_mask_index = penalty_scores.index(min(penalty_scores))
        best_mask_pattern = mask_patterns[best_mask_index]

        for row in range(len(qr_matrix)):
            for column in range(len(qr_matrix[row])):
                if is_data_matrix[row][column]:
                    if best_mask_pattern(row, column):
                        qr_matrix[row][column] ^= 1  # Apply the best mask pattern

        print(f"Selected mask pattern: {best_mask_index} with penalty score: {penalty_scores[best_mask_index]}")
        return best_mask_index


def draw_qr_code_matrix(image: Image.Image, qr_matrix):
    # Draw the QR code matrix onto the image
    for i in range(len(qr_matrix)):
        for j in range(len(qr_matrix[i])):
            if qr_matrix[i][j] == 1:
                image.putpixel((j + 4, i + 4), (0, 0, 0))  # Black pixel
            elif qr_matrix[i][j] == 0:
                image.putpixel((j + 4, i + 4), (255, 255, 255))  # White pixel
            elif qr_matrix[i][j] == 3:
                image.putpixel((j + 4, i + 4), (255, 0, 0))  # Red pixel for reserved areas
            else:
                image.putpixel((j + 4, i + 4), (0, 0, 255))  # Blue pixel for uninitialized areas


def generate_qr_code_image(qr_code_data: QRCodeData, output_file: str, mask_pattern: int=None):
    # Generate a blue image with the qr code size
    image = Image.new('RGB', ((((qr_code_data.version - 1) * 4) + 21) + 4 * 2, (((qr_code_data.version - 1) * 4) + 21) + 4 * 2), color='white')

    # Matrix representing the QR code (1 for black, 0 for white)
    qr_matrix = [[2 for _ in range(((qr_code_data.version - 1) * 4) + 21)] for _ in range(((qr_code_data.version - 1) * 4) + 21)]

    # Boolean matrix to keep track of which positions in the QR code matrix are occupied by data bits (True) or reserved for patterns and format/version information (False)
    is_data_matrix = [[True for _ in range(((qr_code_data.version - 1) * 4) + 21)] for _ in range(((qr_code_data.version - 1) * 4) + 21)]

    # Add finder patterns to the QR code matrix
    add_finder_patterns(qr_matrix, is_data_matrix)

    # Add separator patterns (white space) around the finder patterns
    add_separator_patterns(qr_matrix, is_data_matrix)

    # Add alignment patterns
    add_alignment_patterns(qr_matrix, is_data_matrix, qr_code_data.version)

    # Add timing patterns
    add_timing_patterns(qr_matrix, is_data_matrix)

    # Add dark module (black square) at the bottom-left corner of the QR code matrix
    add_dark_module(qr_matrix, is_data_matrix)

    # Reserve space for format and version information
    reserve_format_and_version_info(qr_matrix, is_data_matrix, qr_code_data.version)

    # Add the data bits
    add_data_bits(qr_matrix, qr_code_data.final_bit_stream)

    # Mask the data bits
    used_mask_pattern = mask_data_bits(qr_matrix, is_data_matrix, mask_pattern)

    # Place format and version modules
    add_format_and_version_info(qr_matrix, is_data_matrix, qr_code_data.version, qr_code_data.error_correction_level, used_mask_pattern)

    # Draw the QR code matrix onto the image
    draw_qr_code_matrix(image, qr_matrix)

    # Resize the image to make it larger for better visibility
    image = image.resize((image.width * 10, image.height * 10), Image.NEAREST)

    # Save the generated QR code image to the specified output file
    if output_file.endswith('.png'):
        image.save(output_file)
        print(f"QR code generated and saved as {output_file}")
    else:
        print(f"Output file {output_file} does not have a .png extension. Saving as qr_code.png instead.")
        output_file = 'qr_code.png'
        image.save(output_file)


def generate_qr_code(input_data: str, output_file: str="qr.png", version: int=None, error_correction_level: str="L", mask_pattern: int=None):
    qr_code_data = create_qr_code_message(input_data=input_data, qr_code_version=version, error_correction_level=error_correction_level)
    generate_qr_code_image(qr_code_data, output_file, mask_pattern)


if __name__ == "__main__":
    input_data = input("Enter the data to encode in the QR code: ")
    #output_file = input("Enter the output file name (e.g., qr_code.png): ")
    generate_qr_code(input_data=input_data, output_file='qr_code.png', version=None, error_correction_level='H', mask_pattern=None)

