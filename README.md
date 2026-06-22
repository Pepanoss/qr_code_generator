# QR Code Generator

A custom QR code generator built in Python that generates qr code images from any text.

---

## Features

* Generate QR codes from any text input
* Supports QR **version selection**
* Configurable **error correction levels (L, M, Q, H)**
* Supports **mask pattern selection**
* Generates QR code images using PIL
* Uses Reed-Solomon error correction (`reedsolo`)

---

## Requirements

Install dependencies using:

```bash id="req1"
pip install -r requirements.txt
```

### Or install manually:

```bash id="req2"
pip install reedsolo pillow
```

---

## How to Run

Run the program using:

```bash id="run1"
python qr_generator.py
```

You will be prompted to enter the data you want to encode:

```text id="run2"
Enter the data to encode in the QR code:
```

Example:

```text id="run3"
Enter the data to encode in the QR code: https://github.com
```

The generated QR code will be saved as:

```text id="run4"
qr_code.png
```

---

## Configuration

You can modify QR generation settings directly in `qr_generator.py`:

```python id="cfg1"
generate_qr_code(
    input_data=input_data,
    output_file="qr_code.png",
    version=None,
    error_correction_level="H",
    mask_pattern=None
)
```

### Parameters:

* **input_data** → Text to encode
* **output_file** → Output image filename
* **version** → QR version (None = auto)
* **error_correction_level**

  * `L` = Low
  * `M` = Medium
  * `Q` = Quartile
  * `H` = High
* **mask_pattern** → Optional manual mask selection

---

## Technologies Used

* Python
* PIL (Pillow) – image generation
* reedsolo – Reed-Solomon error correction

---

## Output Example

After running the script, a QR code image (`qr_code.png`) is generated and can be scanned using any QR scanner.

Here is a example image of a QR code with input text `www.github.com` with H error corection level and automatic version and mask selection.

<img width="330" height="330" alt="qr_code" src="https://github.com/user-attachments/assets/ec7a1621-7044-4960-b8d2-744652811f2b" />



