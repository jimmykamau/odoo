# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.
import base64
import io

from PIL import Image
from random import randrange

from odoo.tools.translate import _


# Preload PIL with the minimal subset of image formats we need
Image.preinit()
Image._initialized = 2

# Maps only the 6 first bits of the base64 data, accurate enough
# for our purpose and faster than decoding the full blob first
FILETYPE_BASE64_MAGICWORD = {
    b'/': 'jpg',
    b'R': 'gif',
    b'i': 'png',
    b'P': 'svg+xml',
}

IMAGE_BIG_SIZE = (1024, 1024)
IMAGE_LARGE_SIZE = (256, 256)
IMAGE_MEDIUM_SIZE = (128, 128)
IMAGE_SMALL_SIZE = (64, 64)

# Arbitraty limit to fit most resolutions, including Nokia Lumia 1020 photo,
# 8K with a ratio up to 16:10, and almost all variants of 4320p
IMAGE_MAX_RESOLUTION = 45e6


def image_process(base64_source, size=(0, 0), verify_resolution=False, quality=80, crop=None, colorize=False, output_format=None):
    """Process the `base64_source` image by executing the given operations and
    return the result as a base64 encoded image.

    :param base64_source: the original image base64 encoded
        Return False immediately if `base64_source` is falsy or if the image
            cannot be identified by Pillow.
        Return the given `base64_source` without change if the image is SVG.
    :type base64_source: string or bytes

    :param size: resize the image
        - The image is never resized above the original image size.
        - The original image ratio is preserved, unless `crop` is also given.
        - If width or height is falsy, it will be computed from the other value
            and from the ratio of the original image.
        - If size is falsy or both width and height are falsy, no resize is done.
    :type max_width: tuple (width, height)

    :param verify_resolution: if True, make sure the original image size is not
        excessive before starting to process it. The max allowed resolution is
        defined by `IMAGE_MAX_RESOLUTION`.
    :type verify_resolution: bool

    :param quality: quality setting to apply.
        - Ignored if image is not JPEG.
        - 1 is worse, 95 is best. Default to 80.
    :type quality: int

    :param crop: crop the image.
        Instead of preserving the ratio of the original image, this will force
        the output to take the ratio of the given `size`. Both `size` width
        and height have to be defined for `crop` to work.
        The value of `crop` defines where to crop: 'center', 'top', 'bottom'.
        Default to 'center' if truthy.
    :type crop: string

    :param colorize: replace the trasparent background by a random color
    :type colorize: bool

    :param output_format: the output format. Can be PNG, JPEG or GIF.
        Default to the format of the original image.
        BMP is converted to PNG, other formats are converted to JPEG.
    :type output_format: string

    :return: image after the operations have been applied, base64 encoded
    :rtype: bytes

    :raise: ValueError if `verify_resolution` is True and the image is too large
    :raise: binascii.Error: if the base64 is incorrect
    :raise: OSError if the image can't be identified by PIL
    """
    if not base64_source:
        return False
    if base64_source[:1] == b'P':
        # don't process SVG
        return base64_source

    image = base64_to_image(base64_source)

    w, h = image.size
    if verify_resolution and w * h > IMAGE_MAX_RESOLUTION:
        raise ValueError(_("Image size excessive, uploaded images must be smaller than %s million pixels.") % str(IMAGE_MAX_RESOLUTION / 10e6))

    # get the format of the original image (must be done before resize)
    output_format = (output_format or image.format).upper()
    if output_format == 'BMP':
        output_format = 'PNG'
    elif output_format not in ['PNG', 'JPEG', 'GIF']:
        output_format = 'JPEG'

    opt = {'format': output_format}

    if size and (size[0] or size[1]):
        w, h = image.size
        asked_width = size[0] or (w * size[1]) // h
        asked_height = size[1] or (h * size[0]) // w

        if crop:
            # We want to keep as much of the image as possible -> at least one
            # of the 2 crop dimensions always has to be the same value as the
            # original image.
            # The target size will be reached with the following resize.
            if w / asked_width > h / asked_height:
                new_w, new_h = w, (asked_height * w) // asked_width
            else:
                new_w, new_h = (asked_width * h) // asked_height, h

            # No cropping above image size.
            if new_w > w:
                new_w, new_h = w, (new_h * w) // new_w
            if new_h > h:
                new_w, new_h = (new_w * h) // new_h, h

            # Corretly place the center of the crop, by default in the center
            # (50% width, 50% height).
            center_x = 0.5
            center_y = 0.5
            if crop == 'top':
                center_y = 0
            elif crop == 'bottom':
                center_y = 1
            x_offset = (w - new_w) * center_x
            h_offset = (h - new_h) * center_y

            image = image.crop((x_offset, h_offset, x_offset + new_w, h_offset + new_h))

        image.thumbnail((asked_width, asked_height), Image.LANCZOS)

    if colorize:
        original = image
        color = (randrange(32, 224, 24), randrange(32, 224, 24), randrange(32, 224, 24))
        image = Image.new('RGB', original.size)
        image.paste(color, box=(0, 0) + original.size)
        image.paste(original, mask=original)

    if output_format == 'PNG':
        opt['optimize'] = True
        alpha = False
        if image.mode in ('RGBA', 'LA') or (image.mode == 'P' and 'transparency' in image.info):
            alpha = image.convert('RGBA').split()[-1]
        if image.mode != 'P':
            # Floyd Steinberg dithering by default
            image = image.convert('RGBA').convert('P', palette=Image.WEB, colors=256)
        if alpha:
            image.putalpha(alpha)
    if output_format == 'JPEG':
        opt['optimize'] = True
        opt['quality'] = quality
    if output_format == 'GIF':
        opt['optimize'] = True

    if image.mode not in ["1", "L", "P", "RGB", "RGBA"] or (output_format == 'JPEG' and image.mode == 'RGBA'):
        image = image.convert("RGB")

    return image_to_base64(image, **opt)

# ----------------------------------------
# Image resizing
# ----------------------------------------


def image_resize_image(base64_source, size=IMAGE_BIG_SIZE, filetype=None):
    return image_process(base64_source, size=size, output_format=filetype)


def image_optimize_for_web(base64_source, max_width=0, quality=80):
    return image_process(base64_source, size=(max_width, 0), verify_resolution=True, quality=quality)


def image_resize_image_big(base64_source, filetype=None):
    return image_process(base64_source, size=IMAGE_BIG_SIZE, output_format=filetype)


def image_resize_image_large(base64_source, filetype=None):
    return image_process(base64_source, size=IMAGE_LARGE_SIZE, output_format=filetype)


def image_resize_image_medium(base64_source, filetype=None):
    return image_process(base64_source, size=IMAGE_MEDIUM_SIZE, output_format=filetype)


def image_resize_image_small(base64_source, filetype=None):
    return image_process(base64_source, size=IMAGE_SMALL_SIZE, output_format=filetype)


def crop_image(base64_source, size, type='center', image_format=None):
    return image_process(base64_source, size=size, crop=type, output_format=image_format)


# ----------------------------------------
# Colors
# ---------------------------------------

def image_colorize(base64_source):
    return image_process(base64_source, colorize=True)


# ----------------------------------------
# Misc image tools
# ---------------------------------------

def base64_to_image(base64_source):
    """Return a PIL image from the given `base64_source`.

    :param base64_source: the image base64 encoded
    :type base64_source: string or bytes

    :return: the PIL image
    :rtype: PIL.Image

    :raise: binascii.Error: if the base64 is incorrect
    :raise: OSError if the image can't be identified by PIL
    """
    return Image.open(io.BytesIO(base64.b64decode(base64_source)))


def image_to_base64(image, format, **params):
    """Return a base64_image from the given PIL `image` using `params`.

    :param image: the PIL image
    :type image: PIL.Image

    :param params: params to expand when calling PIL.Image.save()
    :type params: dict

    :return: the image base64 encoded
    :rtype: bytes
    """
    stream = io.BytesIO()
    image.save(stream, format=format, **params)
    return base64.b64encode(stream.getvalue())


def is_image_size_above(base64_source, size=IMAGE_BIG_SIZE):
    """Return whether or not the size of the given image `base64_source` is
    above the provided `size` (tuple: width, height).
    """
    if not base64_source:
        return False
    if base64_source[:1] == b'P':
        # False for SVG
        return False
    image = base64_to_image(base64_source)
    width, height = image.size
    return width > size[0] or height > size[1]


def image_guess_size_from_field_name(field_name):
    """Attempt to guess the image size based on `field_name`.

    If it can't be guessed, return (0, 0) instead.

    :param field_name: the name of a field
    :type field_name: string

    :return: the guessed size
    :rtype: tuple (width, height)
    """
    suffix = 'big' if field_name == 'image' else field_name.split('_')[-1]
    if suffix == 'big':
        return IMAGE_BIG_SIZE
    if suffix == 'large':
        return IMAGE_LARGE_SIZE
    if suffix == 'medium':
        return IMAGE_MEDIUM_SIZE
    if suffix == 'small':
        return IMAGE_SMALL_SIZE
    return (0, 0)


def image_get_resized_images(base64_source,
        big_name='image', large_name='image_large', medium_name='image_medium', small_name='image_small'):
    """ Standard tool function that returns a dictionary containing the
        big, medium, large and small versions of the source image.

        :param {..}_name: key of the resized image in the return dictionary;
            'image', 'image_large', 'image_medium' and 'image_small' by default.
            Set a key to False to not include it.

        Refer to image_resize_image for the other parameters.

        :return return_dict: dictionary with resized images, depending on
            previous parameters.
    """
    return_dict = dict()
    if big_name:
        return_dict[big_name] = image_resize_image_big(base64_source)
    if large_name:
        return_dict[large_name] = image_resize_image_large(base64_source)
    if medium_name:
        return_dict[medium_name] = image_resize_image_medium(base64_source)
    if small_name:
        return_dict[small_name] = image_resize_image_small(base64_source)
    return return_dict


def image_resize_images(vals,
        return_big=True, return_large=False, return_medium=True, return_small=True,
        big_name='image', large_name='image_large', medium_name='image_medium', small_name='image_small'):
    """ Update ``vals`` with image fields resized as expected. """
    big_image = vals.get(big_name)
    large_image = vals.get(large_name)
    medium_image = vals.get(medium_name)
    small_image = vals.get(small_name)

    biggest_image = big_image or large_image or medium_image or small_image

    if biggest_image:
        vals.update(image_get_resized_images(biggest_image,
            big_name=return_big and big_name, large_name=return_large and large_name, medium_name=return_medium and medium_name, small_name=return_small and small_name))
    elif any(f in vals for f in [big_name, large_name, medium_name, small_name]):
        if return_big:
            vals[big_name] = False
        if return_large:
            vals[large_name] = False
        if return_medium:
            vals[medium_name] = False
        if return_small:
            vals[small_name] = False


def limited_image_resize(base64_source, width=None, height=None, crop=False):
    return image_process(base64_source, size=(width, height), crop=crop)


def image_data_uri(base64_source):
    """This returns data URL scheme according RFC 2397
    (https://tools.ietf.org/html/rfc2397) for all kind of supported images
    (PNG, GIF, JPG and SVG), defaulting on PNG type if not mimetype detected.
    """
    return 'data:image/%s;base64,%s' % (
        FILETYPE_BASE64_MAGICWORD.get(base64_source[:1], 'png'),
        base64_source.decode(),
    )


if __name__=="__main__":
    import sys

    assert len(sys.argv)==3, 'Usage to Test: image.py SRC.png DEST.png'

    img = base64.b64encode(open(sys.argv[1],'rb').read())
    new = image_resize_image(img, (128,100))
    open(sys.argv[2], 'wb').write(base64.b64decode(new))
