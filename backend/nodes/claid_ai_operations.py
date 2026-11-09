"""Claid v1 request structures from https://api.claid.ai/docs-v1.json.

Only request models are represented here; responses are returned as provider JSON.
"""
from __future__ import annotations
from typing import Any, Literal, Optional, Union
from pydantic import BaseModel, ConfigDict, Field, field_validator

class _Request(BaseModel):
    model_config = ConfigDict(extra="allow", hide_input_in_errors=True)

StorageType = Literal['web_folder', 's3', 'gcs']

class AWSCredentials(_Request):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    access_key: str = Field(..., title='Access Key', description='Access Key', min_length=1)
    secret_access_key: str = Field(..., title='Secret Access Key', description='Secret Access Key', min_length=1)


class S3Parameters_Pydantic(_Request):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    path: Optional[str] = Field(None, title='Path', description="An optional relative path that is prepended to the image request path when building the image's path.")
    bucket: str = Field(..., title='Bucket', description='A global Amazon S3 bucket name.', min_length=1)
    credentials: AWSCredentials = Field(...)


class GCPCredentials(_Request):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    access_key: str = Field(..., title='Access Key', description='Access Key', min_length=1)
    secret_access_key: str = Field(..., title='Secret Access Key', description='Secret Access Key', min_length=1)


class GCSParameters_Pydantic(_Request):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    path: Optional[str] = Field(None, title='Path', description="An optional relative path that is prepended to the image request path when building the image's path.")
    bucket: str = Field(..., title='Bucket', description='A global GCS bucket name.', min_length=1)
    credentials: GCPCredentials = Field(...)


class WebFolderParameters_Pydantic(_Request):
    base_url: str = Field(..., title='Base Url')


class StorageIn_Pydantic(_Request):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    name: str = Field(..., title='The unique name of storage', description="The name of storage in Claid. Note: it doesn't have to be the same as a global name of a bucket.", max_length=50)
    type: StorageType = Field(...)
    parameters: Union[S3Parameters_Pydantic, GCSParameters_Pydantic, WebFolderParameters_Pydantic] = Field(..., title='Parameters', description="Global parameters of storage (as opposed to Claid's internal properties, such as `name` and `type`)")


class AWSCredentialsUpdate(_Request):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    access_key: Optional[str] = Field(None, title='Access Key', description='An optional Access Key', min_length=1)
    secret_access_key: Optional[str] = Field(None, title='Secret Access Key', description='An optional Secret Access Key', min_length=1)


class S3ParametersUpdate_Pydantic(_Request):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    path: Optional[str] = Field(None, title='Path', description="An optional relative path that is prepended to the image request path when building the image's path.")
    bucket: Optional[str] = Field(None, title='Bucket', description='An optional global Amazon S3 bucket name.', min_length=1)
    credentials: Optional[AWSCredentialsUpdate] = Field(None)


class GCPCredentialsUpdate(_Request):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    access_key: Optional[str] = Field(None, title='Access Key', description='An optional Access Key', min_length=1)
    secret_access_key: Optional[str] = Field(None, title='Secret Access Key', description='An optional Secret Access Key', min_length=1)


class GCSParametersUpdate_Pydantic(_Request):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    path: Optional[str] = Field(None, title='Path', description="An optional relative path that is prepended to the image request path when building the image's path.")
    bucket: Optional[str] = Field(None, title='Bucket', description='An optional global GCS bucket name.', min_length=1)
    credentials: Optional[GCPCredentialsUpdate] = Field(None)


class StorageInUpdate_Pydantic(_Request):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    name: Optional[str] = Field(None, title='The unique name of storage', max_length=50)
    type: Optional[StorageType] = Field(None)
    parameters: Optional[Union[S3ParametersUpdate_Pydantic, GCSParametersUpdate_Pydantic, WebFolderParameters_Pydantic]] = Field(None, title='Parameters')


DecompressEnum = Literal['moderate', 'strong', 'auto']

UpscaleEnum = Literal['smart_enhance', 'smart_resize', 'faces', 'digital_art', 'photo']

PhotoVersionEnum = Literal['1', '2', '3']

class UpscalePhotoOptions(_Request):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    type: Literal['photo'] = Field(..., title='Type')
    version: PhotoVersionEnum = Field(..., title='Version', description='Upscales the image with specified version of photo upscaling neural network. \n\n| Value | Description |\n| --- | --- |\n| `"1"` | Is deprecated and not recommended.|\n| `"2"` | Used for restoring image quality that is taken by mobile devices or digital camera.|\n| `"3"` | Used for restoring image quality, a bit more aggressively than "2".|\n')


class RestorationsOptions(_Request):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    decompress: Optional[DecompressEnum] = Field(None, description='The decompress operation allows you to remove distortion and artifacts caused by image compression methods. It can be used in conjunction with the upscale operation to prepare an image for upscaling.\n\n| Value | Description |\n| --- | --- |\n| null | DEFAULT. No restoration applied.|\n| `"moderate"` | Removes JPEG artifacts from the image.|\n| `"strong"` | Removes JPEG artifacts more aggressively than "moderate".|\n| `"auto"` | Automatically detects and remove JPEG artifacts if needed.|')
    upscale: Optional[Union[UpscaleEnum, UpscalePhotoOptions]] = Field(None, title='Upscale', description='The upscale operation allows you to improve the overall quality of an image by rendering out new pixels. The upscale operation works along with resizing through numeric or percentage values for upscaling.')
    polish: Optional[bool] = Field(None, title='Polish image', description='If `true`, polishes an image')


class HdrOptions(_Request):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    intensity: Optional[int] = Field(None, title='Intensity', description='HDR effect intensity.', ge=0.0, le=100.0)
    stitching: Optional[bool] = Field(None, title='Stitching', description='Set to true for seamless HDR effect on stitched 360 photos.')


class AdjustmentsOptions(_Request):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    hdr: Optional[Union[int, HdrOptions]] = Field(None, title='Hdr', description='Balances out colors and lighting. Allows to turn on `stitching` for stitched 360 photos.')
    exposure: Optional[int] = Field(None, title='Exposure', description='Decrease (negative integer) or increase (positive integer) exposure.', ge=-100.0, le=100.0)
    saturation: Optional[int] = Field(None, title='Saturation', description='Decrease (negative integer) or increase (positive integer) saturation.', ge=-100.0, le=100.0)
    contrast: Optional[int] = Field(None, title='Contrast', description='Decrease (negative integer) or increase (positive integer) contrast.', ge=-100.0, le=100.0)
    sharpness: Optional[int] = Field(None, title='Sharpness', description='Increase sharpness.', ge=0.0, le=100.0)


class BackgroundSelectiveOptions(_Request):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    object_to_keep: str = Field(..., title='Object To Keep', description='Specify an object to keep on the image.', min_length=3, max_length=128)


BackgroundCategoryEnum = Literal['general', 'cars', 'products']

class BackgroundRemovalOptions(_Request):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    clipping: Optional[bool] = Field(None, title='Clip to object', description='If `true` image will be cropped up to the edges of the foreground object.')
    selective: Optional[BackgroundSelectiveOptions] = Field(None, title='Selective', description='Allows to select an object to keep on the image and remove the background around it.')
    category: Optional[BackgroundCategoryEnum] = Field(None, title='Category', description='The background removal category hints the type of objects on the image.')


BackgroundEnum = Literal['transparent']

BackgroundBlurTypeEnum = Literal['regular', 'lens']

BackgroundBlurLevelEnum = Literal['low', 'medium', 'high']

class BackgroundBlurOptions(_Request):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    selective: Optional[BackgroundSelectiveOptions] = Field(None, title='Selective', description='Allows to select an object to keep on the image and blur the background around it.')
    category: Optional[BackgroundCategoryEnum] = Field(None, description='Selects the category of objects on the image: \n\n| Value | Description |\n| --- | --- |\n| `"general"` | The category that is suitable for all objects and is used by default.|\n| `"cars"` | The advanced category that will have better results for removing the background with cars on foreground.|\n| `"products"` | The advanced category that will have better results for background removal of various types of products and groceries.|\n')
    type: Optional[BackgroundBlurTypeEnum] = Field(None, description='Selects the type of blur to be applied to the background: \n\n| Value | Description |\n| --- | --- |\n| `"regular"` | Gaussian blur. Creates an effect of laying a translucent material like vellum on top of the image background, is used by default.|\n| `"lens"` | Lens blur with linear focus. Mimics the blur applied to a photo when a wide aperture is used to achieve a narrow depth of field, so that the foreground objects stands out.|\n')
    level: Optional[BackgroundBlurLevelEnum] = Field(None, description='Selects the level of blur strength to be applied to the background: \n\n| Value | Description |\n| --- | --- |\n| `"low"` | Low blur strength.|\n| `"medium"` | Medium blur strength, is used by default.|\n| `"high"` | High blur strength.|\n')


class BackgroundOptions(_Request):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    remove: Optional[Union[bool, BackgroundRemovalOptions]] = Field(None, title='Remove', description='Allows to turn on and configure image background removal.')
    color: Optional[Union[str, BackgroundEnum]] = Field(None, title='Color', description='Color as a hexadecimal. Sets a background color. Defaults to the `#ffffff` (white) color, or `transparent` if an input image has transparency.')
    blur: Optional[Union[bool, BackgroundBlurOptions]] = Field(None, title='Blur', description='Allows to turn on and configure image background blurring.')


SizesEnum = Literal['auto']

FitEnum = Literal['crop', 'cover', 'bounds', 'canvas', 'outpaint']

FitCropEnum = Literal['center', 'smart']

class CropOptions(_Request):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    type: Literal['crop'] = Field(..., title='Type')
    crop: Optional[FitCropEnum] = Field(None, title='Crop mode', description='Selects the crop mode: \n\n| Value | Description |\n| --- | --- |\n| `"center"` | Cropping relative to the center of the image.|\n| `"smart"` | Content aware image cropping.|\n')


class CoverOptions(_Request):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    type: Literal['cover'] = Field(..., title='Type')


class BoundsOptions(_Request):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    type: Literal['bounds'] = Field(..., title='Type')


class CanvasOptions(_Request):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    type: Literal['canvas'] = Field(..., title='Type')


class OutpaintOptions(_Request):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    type: Literal['outpaint'] = Field(..., title='Type')
    feathering: Optional[str] = Field(None, title='Feathering', description='Percentage in string format. Examples: `"60%"`, `"200%"`', pattern='^[1-9][0-9]+[%]$|^[0-9][%]$')
    outpaint_by: Optional[str] = Field(None, title='Outpaint By', description='The amount of outpainting to be applied to the image. Should be a string with one or two values separated by space. Each value can be in pixels (e.g. `"100px"`) or in percentages (e.g. `"20%"`).\nIf two values are provided, the first value is for the width and the second value is for the height.\nIf only one value is provided, it will be applied to both width and height.\nIf not provided, the outpainting will be applied in one direction only based on `fit.width` and `fit.height`.\nExamples: `"10%"`, `"5% 15%"`, `"5% 0%"`, `"1024px"`, `"1024px 512px"`, `"0px 1024px"`.')


class ResizingOptions(_Request):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    width: Optional[Union[int, SizesEnum, str]] = Field(None, title='Width', description='Width of output image. Should be of the same type as `height`, or `"auto"`.')
    height: Optional[Union[int, SizesEnum, str]] = Field(None, title='Height', description='Height of output image. Should be of the same type as `width`, or `"auto"`.')
    fit: Optional[Union[FitEnum, CropOptions, CoverOptions, BoundsOptions, CanvasOptions, OutpaintOptions]] = Field(None, title='Fit', description='The fit parameter controls how the image will be constrained within the provided size, relative to the `width` and `height`. By default, `fit` mode is `"crop"`.')


class PrivacyOptions(_Request):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    blur_car_plate: Optional[bool] = Field(None, title='Blur Car Plate', description='If `true`, blurs car plate.')
    identity_crop: Optional[bool] = Field(None, title='Identity Crop', description="Removes a person's face from the image by cutting everything above the mouth.")


class StyleTransferOptions(_Request):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    style_reference_image: str = Field(..., title='Style Reference Image', description='URL of the image to be used as a style reference.')
    prompt: Optional[str] = Field(None, title='Prompt', description='Text prompt to adjust the style transfer output.', min_length=3, max_length=1024)
    depth_strength: Optional[float] = Field(None, title='Depth Strength', description='The denoising strength determines the degree of overall composition and shape preservation.', ge=0.0, le=1.0)
    denoising_strength: Optional[float] = Field(None, title='Denoising Strength', description='The denoising strength determines the degree of color and texture modification.', ge=0.0, le=1.0)
    style_strength: Optional[float] = Field(None, title='Style Strength', description='The style strength determines the degree of overall style intensity as taken from the reference.', ge=0.0, le=1.0)


class GenerativeOptions(_Request):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    style_transfer: Optional[StyleTransferOptions] = Field(None, title='Style Transfer', description='Apply style from a reference image.')


class ImageOperations(_Request):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    restorations: Optional[RestorationsOptions] = Field(None, title='Restorations', description='Restore lost details and decompress image with a wide range of AI-powered neural networks. By default, both operations is turned off.')
    adjustments: Optional[AdjustmentsOptions] = Field(None, title='Adjustments', description='Change image histogram: set brightness, saturation, dynamic range, balance out colors and lighting. By default, no adjustments are made.')
    background: Optional[BackgroundOptions] = Field(None, title='Background', description='Remove the background and set a solid color. By default, no changes are made.')
    resizing: Optional[ResizingOptions] = Field(None, title='Resizing', description='Set the final image size. Crop or fit image in canvas. By default, API will perform all calculations respecting the original image aspect ratio.')
    padding: Optional[str] = Field(None, title='Padding', description='Add a space around the object equally to each of 4 sides, or for height&width separately. Can not be bigger than half of image width/height. By default, padding is not applied.')
    privacy: Optional[PrivacyOptions] = Field(None, title='Privacy', description='Manage sensitive information on the image.')
    generative: Optional[GenerativeOptions] = Field(None, title='Generative', description='Transform the image using generative models.')


FormatEnum = Literal['jpeg', 'png', 'webp', 'avif', 'tiff']

class FormatJpegOptions(_Request):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    type: Literal['jpeg'] = Field(..., title='Type', description='Must have value `"jpeg"`')
    quality: Optional[int] = Field(None, title='Quality', ge=1.0, le=100.0)
    progressive: Optional[bool] = Field(None, title='Progressive', description="Progressive JPEG loads in a browser in successive waves until a clear picture is formed. This improves image's loading speed.")


FormatCompressionLevelEnum = Literal['fast', 'best', 'optimal']

class FormatPngOptions(_Request):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    type: Literal['png'] = Field(..., title='Type', description='Must have value `"png"`')
    compression: Optional[FormatCompressionLevelEnum] = Field(None, description='Specifies compression effort that will be applied during the PNG image encoding. Should have one of values: `"fast"`, `"best"`, or `"optimal"`. Defaults to `"optimal"`.')


WebpCompressionEnum = Literal['lossy', 'lossless']

class WebpLossyCompressionOptions(_Request):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    type: Literal['lossy'] = Field(..., title='Type', description='Must have value `"lossy"`')
    quality: Optional[int] = Field(None, title='Quality', ge=1.0, le=100.0)


class WebpLosslessCompressionOptions(_Request):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    type: Literal['lossless'] = Field(..., title='Type', description='Must have value `"lossless"`')


class FormatWebpOptions(_Request):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    type: Literal['webp'] = Field(..., title='Type', description='Must have value `"webp"`')
    compression: Optional[Union[WebpCompressionEnum, WebpLossyCompressionOptions, WebpLosslessCompressionOptions]] = Field(None, title='Compression', description="The WEBP codec supports both lossless and lossy modes of operation, so you can select the one that is appropriate for your goals. Lossy compression allows you to reduce the size of the image significantly in exchange for some loss of data, reducing the quality of an image. You can specify the amount of loss you are willing to accept. By default it's set to to 75. Lossless compression allows you to save maximum image details in exchange for a significantly increased file size.")


AvifCompressionEnum = Literal['lossy', 'lossless']

class AvifLossyCompressionOptions(_Request):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    type: Literal['lossy'] = Field(..., title='Type', description='Must have value `"lossy"`')
    quality: Optional[int] = Field(None, title='Quality', ge=1.0, le=100.0)


class AvifLosslessCompressionOptions(_Request):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    type: Literal['lossless'] = Field(..., title='Type', description='Must have value `"lossless"`')


class FormatAvifOptions(_Request):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    type: Literal['avif'] = Field(..., title='Type', description='Must have value `"avif"`')
    compression: Optional[Union[AvifCompressionEnum, AvifLossyCompressionOptions, AvifLosslessCompressionOptions]] = Field(None, title='Compression', description='The AVIF codec supports both lossless and lossy modes of operation, so you can select the one that is appropriate for your goals. Lossy compression allows you to reduce the size of the image significantly in exchange for some loss of data, reducing the quality of an image. You can specify the amount of loss you are willing to accept. Lossless compression allows you to save maximum image details in exchange for a significantly increased file size.')


TiffCompressionEnum = Literal['lossy', 'lossless']

class TiffLossyCompressionOptions(_Request):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    type: Literal['lossy'] = Field(..., title='Type', description='Must have value `"lossy"`')
    quality: Optional[int] = Field(None, title='Quality', ge=1.0, le=100.0)


class TiffLosslessCompressionOptions(_Request):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    type: Literal['lossless'] = Field(..., title='Type', description='Must have value `"lossless"`')


class FormatTiffOptions(_Request):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    type: Literal['tiff'] = Field(..., title='Type', description='Must have value `"tiff"`')
    compression: Optional[Union[TiffCompressionEnum, TiffLossyCompressionOptions, TiffLosslessCompressionOptions]] = Field(None, title='Compression', description="The TIFF codec supports both lossless and lossy modes of operation, so you can select the one that is appropriate for your goals. Lossy JPEG compression allows you to reduce the size of the image significantly in exchange for some loss of data, reducing the quality of an image. You can specify the amount of loss you are willing to accept. By default it's set to to 75. Lossless LZW (Lempel-Ziv-Welch) compression allows you to save maximum image details in exchange for a significantly increased file size.")


ColorSpaceEnum = Literal['RGB', 'CMYK']

class RGBColorSpaceOptions(_Request):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    type: Literal['RGB'] = Field(..., title='Type')


CMYKColorProfileEnum = Literal['ISO_Coated', 'ISO_Uncoated', 'USWeb_Coated', 'USWeb_Uncoated']

class CMYKColorSpaceOptions(_Request):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    type: Literal['CMYK'] = Field(..., title='Type')
    color_profile: Optional[CMYKColorProfileEnum] = Field(None, description='Specifies color profile that will be used for color space. \n\nSelects the type of color space profile: \n\n| Value | Description | Paper | Max. total ink (TAC) | Characterisation data | \n| --- | --- | --- | --- | --- |\n| `"ISO_Coated"` | (Coated FOGRA39, ISO 12647-2:2004) Is used by default. Standard for glossy and matte coated paper. | Grades 1 and 2, gloss and matte coated. | 330% | FOGRA39 |\n| `"ISO_Uncoated"` | (Uncoated FOGRA29, ISO 12647-2:2004) Standard for uncoated white natural paper. | Grade 4, uncoated white offset. | 300% | FOGRA29 |\n| `"USWeb_Coated"` | (SWOP2006_Coated3v2) Standard for glossy and matte coated paper in the United States. | Grades 1, 2 and 3 gloss coated, matte coated and uncoated paper. | 300% | CGATS TR003 |\n| `"USWeb_Uncoated"` | (GRACoL 2013 Uncoated) Standard for uncoated white natural paper in the United States. | Grade 4, uncoated white offset. | 260% |  CGATS21-2-CRPC3 |\n')


class MetadataOptions(_Request):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    dpi: Optional[int] = Field(None, title='DPI', description='Dots per inch.')
    color_space: Optional[Union[ColorSpaceEnum, RGBColorSpaceOptions, CMYKColorSpaceOptions]] = Field(None, title='Color Space', description='Specifies desirable color space of the output image. By default, preserves the color space of the original image.')


class ImageOutputOptions(_Request):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    format: Optional[Union[FormatEnum, FormatJpegOptions, FormatPngOptions, FormatWebpOptions, FormatAvifOptions, FormatTiffOptions]] = Field(None, title='Format', description='Converts an image to one of the following formats: `"jpeg"`, `"png"`, `"webp"`, `"avif"`. Selecting *Jpeg Options* allows to specify quality.')
    destination: Optional[str] = Field(None, title='Output URL', description='URL of the output image. If `output` is not defined, we store the output image on our bucket and return the temporary URL. The name of the output file remains the same as the input file. Images are stored for one day.', min_length=1, max_length=4096, json_schema_extra={'format': 'uri'})
    metadata: Optional[MetadataOptions] = Field(None, title='Metadata', description='Defines characteristics of the output image, e.g. DPI.')


class EditRequest(_Request):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    input: str = Field(..., title='Input URL', description='URL of the input image. Should be from 1 to 512 characters. Image must be accessible by our system.', min_length=1, max_length=4096, json_schema_extra={'format': 'uri'})
    operations: ImageOperations = Field(..., title='Operations', description='Customize the editing workflow so that the output images meet your requirements.')
    output: Optional[Union[ImageOutputOptions, str]] = Field(None, title='Output', description='Customize the result output.')


class BatchEditInputOptions(_Request):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    source: str = Field(..., title='Input folder URL', description='URL of the input file or folder. Should be from 1 to 512 characters. Must be accessible by our system.', min_length=1, max_length=4096, json_schema_extra={'format': 'uri'})
    recursive: Optional[bool] = Field(None, title='Recursive', description='If `true`, recursively processes all images in subfolders as well, works only if source is folder. ')


class BatchEditRequest(_Request):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    input: Union[BatchEditInputOptions, str, list[str]] = Field(..., title='Input folder URL or list of image URLs', description='URL of the input file or folder. Should be from 1 to 512 characters. Must be accessible by our system.')
    operations: ImageOperations = Field(..., title='Operations', description='Customize the editing workflow so that the output images meet your requirements.')
    output: Optional[Union[ImageOutputOptions, str]] = Field(None, title='Output folder URL', description='URL of the output folder. If `output` is not defined, we store the output image on our bucket and return the temporary URL. The name of the output file remains the same as the input file. Images are stored for one day.')


class AsyncEditRequest(_Request):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    input: str = Field(..., title='Input URL', description='URL of the input image. Should be from 1 to 512 characters. Image must be accessible by our system.', min_length=1, max_length=4096, json_schema_extra={'format': 'uri'})
    operations: ImageOperations = Field(..., title='Operations', description='Customize the editing workflow so that the output images meet your requirements.')
    output: Optional[Union[ImageOutputOptions, str]] = Field(None, title='Output', description='Customize the result output.')


class ImageGenerateOptions(_Request):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    number_of_images: Optional[int] = Field(None, title='Number of images', description='Number of images to generate. By default 4 images will be generated.', ge=1.0, le=4.0)
    guidance_scale: Optional[float] = Field(None, title='Guidance scale', description='Guidance scale is used to make the generation better match the prompt potentially at the cost of image quality or diversity. Values between 5 and 7 are usually good choices, but sometimes more control is achieved with values such as 12. By default the pipeline uses a guidance scale of 5.', ge=1.0, lt=50.0)


class GenerateRequest(_Request):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    input: str = Field(..., title='Text prompt for image generation', description='Text prompt that will be used to generate image(s). Should be from 3 to 1024 characters. ', min_length=3, max_length=1024)
    options: Optional[ImageGenerateOptions] = Field(None, title='Image generate options', description='Customize the image generation process so that the output images meet your requirements.')
    output: Optional[str] = Field(None, title='Output folder URL', description='URL of the output folder. If `output` is not defined, we store the output image on our bucket and return the temporary URL, in this case images are stored for one day.', min_length=1, max_length=4096, json_schema_extra={'format': 'uri'})


SceneResolutionEnum = Literal['1MP', '2MP']

class SceneCreateAPIOutputIn(_Request):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    number_of_images: Optional[int] = Field(None, title='Number of images', description='Number of images to create. By default 4 images will be created.', ge=1.0, le=4.0)
    destination: Optional[str] = Field(None, title='Output URL', description='URL of the output images. If `output` is not defined, we store the output image on our bucket and return the temporary URL. Images are stored for one day.', min_length=1, max_length=4096, json_schema_extra={'format': 'uri'})
    format: Optional[Union[FormatEnum, FormatJpegOptions, FormatPngOptions, FormatWebpOptions, FormatAvifOptions]] = Field(None, title='Format', description='Converts images to one of the following formats: `"jpeg"`, `"png"`, `"webp"`, `"avif"`. Selecting *Jpeg Options* allows to specify quality.')
    resolution: Optional[SceneResolutionEnum] = Field(None, title='Output resolution', description='Total number of pixels of the output images. The scene aspect ratio is preserved, only the pixel budget changes.\n\n| Value | Description |\n| --- | --- |\n| `"1MP"` | DEFAULT. About 1 megapixel, e.g. 1024x1024 for a 1:1 scene.|\n| `"2MP"` | About 2 megapixels, e.g. 1440x1440 for a 1:1 scene. Only available when `scene.model` is `"v2"` and `scene.effect` is not used.|')


class ObjectPosition(_Request):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    x: Optional[float] = Field(None, title='Horizontal position', description='Relative position on the scene, where 0 is the left edge of the image and 1 is the right edge of the image.', ge=0.0, le=1.0)
    y: Optional[float] = Field(None, title='Vertical position', description='Relative position on the scene, where 0 is the bottom edge of the image and 1 is the top edge of the image.', ge=0.0, le=1.0)


class SceneCreateAPIObjectAbsoluteIn(_Request):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    image_url: str = Field(..., title='Object image file URL', description='URL of the input image. Should be from 1 to 4096 characters. Image must be accessible by our system. For better results, the background of the image should be transparent.', min_length=1, max_length=4096, json_schema_extra={'format': 'uri'})
    placement_type: Optional[Literal['absolute']] = Field(None, title='Placement Type', description='`"absolute"` placement type allows to manually specify the absolute position, scale, and rotation degree of the object on a scene.')
    rotation_degree: Optional[Union[float, int]] = Field(None, title='Degree of object rotation', description='Degree of object rotation on the scene. By default, the object is not rotated. (i.e. 0.0).')
    scale: Optional[Union[int, float]] = Field(None, title='Relative object scale', description='Relative object scale in relation to the scene. By default, the object is scaled to the scene edges. (i.e. 1.0).')
    position: Optional[ObjectPosition] = Field(None, title='Relative object position', description='Relative object position on the scene. By default, the object is positioned at the center of the scene (i.e. x=0.5, y=0.5).')


class SceneCreateAPIObjectOriginalIn(_Request):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    image_url: str = Field(..., title='Object image file URL', description='URL of the input image. Should be from 1 to 4096 characters. Image must be accessible by our system. For better results, the background of the image should be transparent.', min_length=1, max_length=4096, json_schema_extra={'format': 'uri'})
    placement_type: Literal['original'] = Field(..., title='Placement Type', description='`"original"` placement type instructs to use an object position and scale from the input image, meaning this placement method is fully automated and does not require any additional parameters.')


class SceneCreateAPIObjectPaddingIn(_Request):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    image_url: str = Field(..., title='Object image file URL', description='URL of the input image. Should be from 1 to 4096 characters. Image must be accessible by our system. For better results, the background of the image should be transparent.', min_length=1, max_length=4096, json_schema_extra={'format': 'uri'})
    placement_type: Literal['padding'] = Field(..., title='Placement Type', description='`"padding"` placement type allows to add a space around the object equally to each of 4 sides, or for height&width separately.')
    padding: str = Field(..., title='Padding around the object', description='Add a space around the object equally to each of 4 sides, or for height&width separately. Can not be bigger than half of image width/height.')


SceneCreateModelEnum = Literal['v1', 'v2-beta', 'v2']

SceneEffectEnum = Literal['shadows']

ColorEnum = Literal['transparent']

TemplateViewAutoEnum = Literal['auto', 'top', 'front']

SceneAspectRatioEnum = Literal['21:9', '1:1', '4:3', '3:2', '2:3', '5:4', '4:5', '3:4', '16:9', '9:16']

class SceneCreateAPISceneBackgroundEffectIn(_Request):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    model: Optional[SceneCreateModelEnum] = Field(None, title='Scene creation model', description="Selects the scene creation model. By default, the model is 'v1'.")
    effect: SceneEffectEnum = Field(...)
    color: Optional[Union[str, ColorEnum]] = Field(None, title='Product background coloring', description='Color as a hexadecimal.')
    view: Optional[TemplateViewAutoEnum] = Field(None, title='Product viewpoint', description='The position of the viewpoint relative to the scene\n\n| Value | Description |\n| --- | --- |\n| `"top"` | The view is top-down, looking down on the scene from above.|\n| `"front"` | The view is horizontal, looking directly on the scene.|\n| `"auto"` | The view is automatically selected.|')
    aspect_ratio: Optional[SceneAspectRatioEnum] = Field(None, title='Scene aspect ratio', description='Aspect ratio of the scene. By default, the aspect ratio is 1:1.')


class ScenePromptAdvancedIn(_Request):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    text: Optional[str] = Field(None, title='Text prompt for scene creation', description='Text prompt that will be used to create the scene. Should be from 3 to 2048 characters.', min_length=3, max_length=2048)
    generate: Optional[bool] = Field(None, title='Auto-generate prompt', description='If `true`, the prompt will be generated automatically based on the input image.By default, the prompt is not auto-generated. If `true`, the `text` is not allowed.')
    guidelines: Optional[str] = Field(None, title='Guidelines', description='Guidelines for prompt generation. Only available when `generate` is `true`.', min_length=3, max_length=1000)


PreferenceEnum = Literal['fast', 'optimal', 'best']

class SceneCreateAPIScenePromptIn(_Request):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    model: Optional[SceneCreateModelEnum] = Field(None, title='Scene creation model', description="Selects the scene creation model. By default, the model is 'v1'.")
    prompt: Union[str, ScenePromptAdvancedIn] = Field(..., title='Text prompt for scene creation', description='Text prompt that will be used to create the scene. Should be from 3 to 2048 characters.')
    negative_prompt: Optional[str] = Field(None, title='Negative text prompt for scene creation', description='Text prompt that will exclude things from the scene. Should be from 3 to 2048 characters. ', min_length=3, max_length=2048)
    steps: Optional[int] = Field(None, title='Number of inference steps', description='The more inference steps you use, the better the results, but the more steps, the longer it takes to generate. If you want faster results, you can use fewer steps. If you want higher-quality results, you can use more steps. By default each `template_mode` has an optimal `steps` value.', ge=1.0, lt=50.0)
    color: Optional[str] = Field(None, title='Color', description='Color as a hexadecimal. Examples: `"#ffffff"`, `"#000000"`.')
    aspect_ratio: Optional[SceneAspectRatioEnum] = Field(None, title='Scene aspect ratio', description='Aspect ratio of the scene. By default, the aspect ratio is 1:1.')
    preference: Optional[PreferenceEnum] = Field(None, title='Preference control', description='Preference control allows you to balance between generation speed and output image quality. Higher speed decreases image quality but enables quicker experimentation to find the best parameters for your background.\n\n| Value | Description |\n| --- | --- |\n| `"fast"` | Faster generation, lower quality.|\n| `"optimal"` | Balance between speed and quality.|| `"best"` | Highest quality, slower generation.|')


TemplateModeEnum = Literal['transform', 'lock', 'adjust']

TemplateViewEnum = Literal['top', 'front']

class SceneCreateAPISceneTemplateIn(_Request):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    model: Optional[SceneCreateModelEnum] = Field(None, title='Scene creation model', description="Selects the scene creation model. By default, the model is 'v1'.")
    template_mode: Optional[TemplateModeEnum] = Field(None, title='Template mode', description='Selects how closely the result should match the template.\n\n| Value | Description |\n| --- | --- |\n| `"transform"` | Template is transformed according to the prompt and color.|\n| `"adjust"` | Template is slightly adjusted to the product and prompt.|| `"lock"` | Template is preserved with maximum detail.|')
    template_url: str = Field(..., title='Template image file URL', description='URL of the input image. Should be from 1 to 4096 characters. Image must be accessible by our system. Is optional, if `prompt` is specified.', min_length=1, max_length=4096, json_schema_extra={'format': 'uri'})
    color: Optional[str] = Field(None, title='Color', description='Color as a hexadecimal. Examples: `"#ffffff"`, `"#000000"`.')
    view: TemplateViewEnum = Field(..., title='Template viewpoint', description='The position of the viewpoint relative to the scene\n\n| Value | Description |\n| --- | --- |\n| `"top"` | The view is top-down, looking down on the scene from above.|\n| `"front"` | The view is horizontal, looking directly on the scene.|')
    prompt: Optional[Union[str, ScenePromptAdvancedIn]] = Field(None, title='Text prompt for scene creation', description='Text prompt that will be used to create the scene. Should be from 3 to 2048 characters. ')
    negative_prompt: Optional[str] = Field(None, title='Negative text prompt for scene creation', description='Text prompt that will exclude things from the scene. Should be from 3 to 2048 characters. ', min_length=3, max_length=2048)
    steps: Optional[int] = Field(None, title='Number of inference steps', description='The more inference steps you use, the better the results, but the more steps, the longer it takes to generate. If you want faster results, you can use fewer steps. If you want higher-quality results, you can use more steps. By default each `template_mode` has an optimal `steps` value.', ge=1.0, lt=50.0)


class SceneCreateAPIIn(_Request):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    output: Optional[Union[SceneCreateAPIOutputIn, str]] = Field(None, title='Output URL', description='URL of the output images. If `output` is not defined, we store the output image on our bucket and return the temporary URL. Images are stored for one day.')
    object: Union[SceneCreateAPIObjectAbsoluteIn, SceneCreateAPIObjectOriginalIn, SceneCreateAPIObjectPaddingIn] = Field(..., title='Object manipulation', description='Manipulate object on the scene so that the output images meet your requirements.')
    scene: Union[SceneCreateAPISceneBackgroundEffectIn, SceneCreateAPIScenePromptIn, SceneCreateAPISceneTemplateIn] = Field(..., title='Scene customization', description='Customize the scene so that the output images meet your requirements.')


AiEditFormatEnum = Literal['jpeg', 'png']

class AIEditRequestOutputObject(_Request):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    number_of_images: Optional[int] = Field(None, title='Number of images', description='Number of output images.', ge=1.0, le=4.0)
    destination: Optional[str] = Field(None, title='Destination', description='Customize the result output.', min_length=1, max_length=4096, json_schema_extra={'format': 'uri'})
    format: Optional[AiEditFormatEnum] = Field(None, description='Output image format.')


AIEditModelAPI = Literal['v1', 'v2']

AiEditAspectRatio = Literal['1:1', '2:3', '3:2', '3:4', '4:3', '9:16', '16:9', '9:21', '21:9']

class AiEditRequestOptionsObject(_Request):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    model: Optional[AIEditModelAPI] = Field(None, description='Model to be used for generation.')
    prompt: str = Field(..., title='Prompt', description='Prompt for the generation.', min_length=3, max_length=5000)
    aspect_ratio: Optional[AiEditAspectRatio] = Field(None, description='Aspect ratio of the generated images.')
    inference_steps: Optional[int] = Field(None, title='Inference Steps', description='Number of inference steps.', ge=1.0, le=50.0)
    guidance_scale: Optional[float] = Field(None, title='Guidance Scale', description='Guidance scale for the generation.', ge=1.0, le=10.0)


class AiEditAPIRequest(_Request):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    output: Optional[Union[AIEditRequestOutputObject, str]] = Field(None, title='Output', description='Customize output format, destination and number of images.')
    input: str = Field(..., title='Input URL', description='URL of the input image. Image must be accessible by our system.', min_length=1, max_length=4096, json_schema_extra={'format': 'uri'})
    options: AiEditRequestOptionsObject = Field(..., title='Options', description='Customize the generation.')


TryOnAPIFormatEnum = Literal['jpeg', 'png']

class TryOnAPIRequestOutputObject(_Request):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    number_of_images: Optional[int] = Field(None, title='Number of images', description='Number of output images.', ge=1.0, le=4.0)
    destination: Optional[str] = Field(None, title='Destination', description='Customize the result output.', min_length=1, max_length=4096, json_schema_extra={'format': 'uri'})
    format: Optional[TryOnAPIFormatEnum] = Field(None, description='Output image format.')


class TryOnAPIRequestInputOptions(_Request):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    model: Optional[str] = Field(None, title='Input model URL', description='URL of the human model image. Image must be accessible by our system.', min_length=1, max_length=4096, json_schema_extra={'format': 'uri'})
    clothing: list[str] = Field(..., title='Clothing images URLs', description='List of clothing images URLs. Images must be accessible by our system.', min_length=1, max_length=5)


TryOnAPIAspectRatio = Literal['1:1', '2:3', '3:2', '3:4', '4:3', '9:16', '16:9', '21:9', '4:5', '5:4']

class TryOnAPIRequestOptionsObject(_Request):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    pose: Optional[str] = Field(None, title='Pose', description='Pose prompt for the generation.', min_length=3, max_length=5000)
    background: Optional[str] = Field(None, title='Background', description='Background prompt for the generation.', min_length=3, max_length=5000)
    aspect_ratio: Optional[TryOnAPIAspectRatio] = Field(None, description='Aspect ratio of the generated images.')


class TryOnAPIRequest(_Request):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    output: Optional[Union[TryOnAPIRequestOutputObject, str]] = Field(None, title='Output', description='Customize output format, destination and number of images.')
    input: TryOnAPIRequestInputOptions = Field(..., title='Input', description='Input model and clothing images for the generation.')
    options: TryOnAPIRequestOptionsObject = Field(..., title='Options', description='Customize the generation.')


class VideoPromptObject(_Request):
    text: Optional[str] = Field(None, title='Text', description='Prompt for the video.', min_length=3, max_length=5000)
    generate: Optional[bool] = Field(None, title='Generate', description='If `true`, the prompt will be generated automatically based on the input image.By default, the prompt is not auto-generated. If `true`, the `text` is not allowed.')
    guidelines: Optional[str] = Field(None, title='Guidelines', description='Guidelines for prompt generation. Only available when `generate` is `true`.', min_length=3, max_length=1000)


DurationEnum = Literal['5', '10']

class VideoOptionsObject(_Request):
    @field_validator("duration", mode="before")
    @classmethod
    def normalize_duration(cls, value):
        # HTTP docs use numbers; the published schema specifies string enums.
        return str(value) if type(value) is int and value in (5, 10) else value

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    prompt: Union[str, VideoPromptObject] = Field(..., title='Prompt', description='Prompt for the video.')
    negative_prompt: Optional[str] = Field(None, title='Negative Prompt', description='Negative prompt for the video.', min_length=3, max_length=5000)
    duration: Optional[DurationEnum] = Field(None, description='Duration of the video.')
    guidance_scale: Optional[float] = Field(None, title='Guidance Scale', description='Guidance scale for the video.', ge=0.0, le=1.0)


class ImageVideoRequest(_Request):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    output: Optional[str] = Field(None, title='Output', description='Customize the result output.', min_length=1, max_length=4096, json_schema_extra={'format': 'uri'})
    input: str = Field(..., title='Input URL', description='URL of the input image. Image must be accessible by our system.', min_length=1, max_length=4096, json_schema_extra={'format': 'uri'})
    options: VideoOptionsObject = Field(..., title='Options', description='Customize the video.')
