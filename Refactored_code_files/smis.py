import os
import cv2
import numpy as np
from numpy.lib import utils

from models import Student
from utils import TesseractOcrParser

WARP_DIR_NAME = "warp_images"
BINARY_DIR_NAME ="binary_images"
# signing_sheets = "signing_sheets"
signing_sheets = "signing_sheet_1"
COLUMN_IDENTIFIED_DIR_NAME = "column_identify"
CROPPED_IMG_DIR_NAME = "cropped_img"


def drawHoughLines(image, lines, size, color):
    size = size if len(lines) > size else len(lines)
    print(f" number of lines : {size}")
    for line in lines[:size]:
        # print(f" Line : {line}")
        for rho,theta in line:
            a = np.cos(theta)
            b = np.sin(theta)
            x0 = a*rho
            y0 = b*rho
            x1 = int(x0 + 1000*(-b))
            y1 = int(y0 + 1000*(a))
            x2 = int(x0 - 1000*(-b))
            y2 = int(y0 - 1000*(a))

            # print(x1,y1,x2,y2,x0,y0)
            cv2.line(image,(x1,y1),(x2,y2),color,3)
            
            print(f"theta value : {theta} rho : {rho}\n")
            (h, w) = image.shape[:2]
            center = (w // 2, h // 2)
            M = cv2.getRotationMatrix2D(center,np.degrees(theta)-90, 1.0)
            rotated = cv2.warpAffine(image, M, (w, h), flags=cv2.INTER_CUBIC, \
                borderMode=cv2.BORDER_REPLICATE)
        # return rotated
    return image



def preprocess_image(image):
    h, w = image.shape[:2]
    center = (w // 2, h // 2)
    print("Converting the image to gray scale")
    gray_scale_img = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    # Canney detection
    canney_edges = 	cv2.Canny(gray_scale_img, 60, 120, apertureSize = 3)
    hough_lines = cv2.HoughLines(canney_edges, 1, np.pi/180, 40)
    rho,theta = hough_lines[0][0]
    a = np.cos(theta)
    b = np.sin(theta)
    x0 = a*rho
    y0 = b*rho
	
    x1 = int(x0 + 10*(-b))
    y1 = int(y0 + 10*(a))
    x2 = int(x0 - 600*(-b))
    y2 = int(y0 - 600*(a))    

    M = cv2.getRotationMatrix2D(center,np.degrees(theta)-90, 1.0)
    aligned_image = cv2.warpAffine(image, M, (w, h), flags=cv2.INTER_CUBIC, \
		borderMode=cv2.BORDER_REPLICATE)
    return aligned_image


def sort_contours(cnts, method="left-to-right"):
	# initialize the reverse flag and sort index
	reverse = False
	i = 0
	# handle if we need to sort in reverse
	if method == "right-to-left" or method == "bottom-to-top":
		reverse = True
	# handle if we are sorting against the y-coordinate rather than
	# the x-coordinate of the bounding box
	if method == "top-to-bottom" or method == "bottom-to-top":
		i = 1
	# construct the list of bounding boxes and sort them from top to
	# bottom
	boundingBoxes = [cv2.boundingRect(c) for c in cnts]
	(cnts, boundingBoxes) = zip(*sorted(zip(cnts, boundingBoxes),
		key=lambda b:b[1][i], reverse=reverse))
	# return the list of sorted contours and bounding boxes
	return (cnts, boundingBoxes)


def detect_tables_lines(image):
    print("Detecting the table in the image")
    ret, bw_image = cv2.threshold(
        cv2.cvtColor(image, cv2.COLOR_BGR2GRAY), 128, 255, cv2.THRESH_BINARY
    )
    
    threshold_value = cv2.threshold(
        bw_image, 100, 255, cv2.THRESH_BINARY_INV, + cv2.THRESH_OTSU
    )[1]

    # Detecting the boxes
    kernel_length = np.array(image).shape[1] // 80
    # A verticle kernel of (1 X kernel_length), which will detect all the verticle lines from the image.
    verticle_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, kernel_length))
	# A horizontal kernel of (kernel_length X 1), which will help to detect all the horizontal line from the image.
    hori_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (kernel_length, 1))
	# A kernel of (3 X 3) ones.
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    
    # Morphological operation to detect vertical lines from an image
    img_temp1 = cv2.erode(threshold_value, verticle_kernel, iterations=3)
    verticle_lines_img = cv2.dilate(img_temp1, verticle_kernel, iterations=3)
    img_temp2 = cv2.erode(threshold_value, hori_kernel, iterations=3)
    horizontal_lines_img = cv2.dilate(img_temp2, hori_kernel, iterations=3)

    # Weighting parameters, this will decide the quantity of an image to be added to make a new image.
    alpha = 0.5
    beta = 1.0 - alpha
    # This function helps to add two image with specific weight parameter to get a third image as summation of two image.
    img_final_bin = cv2.addWeighted(verticle_lines_img, alpha, horizontal_lines_img, beta, 0.0)
    img_final_bin = cv2.erode(~img_final_bin, kernel, iterations=2)
    (thresh, img_final_bin) = cv2.threshold(img_final_bin, 128,255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)

    # Find contours for image, which will detect all the boxes
    contours, hierarchy = cv2.findContours(img_final_bin, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
    # Sort all the contours by top to bottom.
    return sort_contours(contours, method="top-to-bottom")


def get_contours_under_region(region_coordinates, contours):
    region_x_min, region_y_min, region_x_max, region_y_max = region_coordinates
    detected_contours = []
    for contour in contours:
        x, y, width, heigth = cv2.boundingRect(
            contour,
        )
        if (x > region_x_min) and ((x+width) < region_x_max) and (y > region_y_min) and ((y+heigth) < region_y_max):
            detected_contours.append(contour)
    if len(detected_contours) == 0: raise Exception("Error no contours detected under the region coordinates")
    return detected_contours


def get_student_region(contours):
    # TODO: Remove large contour of page with area validation
    contours = list(contours)[1:]
    max_area = np.array(
        [ cv2.contourArea(contour) for contour in contours ]
    ).argmax()
    x_min, y_min, region_width, region_heigth = cv2.boundingRect(
        contours[max_area],
    )
    cooridnates = x_min, y_min, x_min + region_width, y_min + region_heigth 
    contours = get_contours_under_region(cooridnates, contours)
    return (cooridnates, contours)
    


def parse_student_details(image, contours, region_coordinates, op_path):
    ocrParser = TesseractOcrParser()
    expected_column_name = [
        "studentno", "studentname", "signature",
    ]
    record_coordinate = None
    padding = 20
    region_details = {}
    region_x_min, region_y_min, region_x_max, region_y_max = region_coordinates
    start_x, start_y, start_w, start_h = cv2.boundingRect(contours[0])
    for contour in contours[:5]:
        x, y, w, h = cv2.boundingRect(contour)
        # image = cv2.rectangle(image, (x, y), (x+w, y+h), (255, 0, 0), 5)
        # cropped_cell = image[y-10: y+h+10, x-10: x+w+10]
        cropped_cell = image[y+2: y+h-2, x+2: x+w-2]
        ocr_parsed_text = ocrParser.get_string_from_image(cropped_cell)
        cv2.imwrite(os.path.join(op_path, f"cropped_image_{contours.index(contour)}.jpeg"), cropped_cell)
        
        if ocr_parsed_text.lower() in expected_column_name:
            print(f"Matched ocr : {ocr_parsed_text.lower()}")
            region_details[ocr_parsed_text.lower()] = {
                "coordinates" : (x - padding, y + h - padding, x + w + padding, region_y_max + padding)
            }
            
            if len(region_details.keys()) == 3: break 
    # cv2.imwrite(os.path.join(op_path, f"complete_image.jpeg"), image)
    print(f"Region Details : \n{region_details}\n")
    return region_details
    # record_by_row = []
    # # After removing the header column from contour table
    # student_record_contours = get_contours_under_region(
    #     start_x+padding, start_y+start_w+padding, region_x_max, region_y_max
    # )
    
    # while len(student_record_contours) >= 5:
    #     start_x, start_y, w, h = cv2.boundingRect(student_record_contours[0])
    #     record_contours = get_contours_under_region(
    #         (start_x- padding, start_y - padding, region_x_max+padding, start_y+start_h+padding)
    #     )
    #     for record in record_contours:
    #         x, y, w, h = cv2.boundingRect(contour)
    #         cropped_cell = image[y-10: y+h+10, x-10: x+w+10]
    #         parsed_value = ocrParser.get_string_from_image(cropped_cell)
    #         # TODO: PARSE the record using the student_no, student_name and signature region
    #         # Validate the value with xml values

    #         student_record_contours.remove(record)
        
    # print(f"After parsing the length of student record conours {len(student_record_contours)}\n")



            # # if count == 5:   break
            # count += 1
            # image = cv2.rectangle(image, (x, y), (x+w, y+h), (0, 0, 255), 5)
            # # cropped_cell = image[y-2: y+h+2, x-2: x+w+2]
            # # cv2.imwrite(os.path.join(op_path, f"cropped_image_{idx}.jpeg"),cropped_cell)
            # idx += 1
            # x_coordinates.append(x)
            # y_coordinates.append(y)
            # # image = cv2.circle(image, (x, y), radius=5, color=(0, 0, 255), thickness=5)
            # print(f"Pixel values x_min: {x} y_min : {y} x_max: {x+w} y_max : {y+h}")

    

if __name__ == "__main__":

    fileName = "1.jpeg"
    in_file = "page.jpg"
    pre_file ="pre.png"
    out_file ="out.png"
    # original_dir_path = r"/home/ArunaSudhan/Documents/NSBM Lec/CGV/Assignment/code_base/images"

    current_working_dir = os.getcwd()
    original_dir_path = os.path.join(os.getcwd(), "images")

    output_dir_path = os.path.join(current_working_dir, "output")
    if not os.path.exists(output_dir_path):
        os.makedirs(output_dir_path)
    

    img = cv2.imread(
        os.path.join(original_dir_path, fileName)
    )

    aligned_image = preprocess_image(img)

    contours, boundingBoxes = detect_tables_lines(aligned_image)
    region_cooridnates, student_region_contours = get_student_region(
        contours,
    )

    region_details = parse_student_details(
        aligned_image,
        student_region_contours, # Retrieves the coordinates under the region
        region_cooridnates, 
        output_dir_path
    )


    # TODO TO TEST THE REGION AFTER PARSING FOR TEXT
    color_rank = {"studentno": (0, 0, 255), "studentname": (0, 255, 0), "signature": (255, 0, 0)}
    image = aligned_image.copy()
    for region in region_details.keys():
        if region_details[region] is not None:
            image = cv2.rectangle(
                image, 
                (region_details[region]["coordinates"][0], region_details[region]["coordinates"][1]), 
                (region_details[region]["coordinates"][2], region_details[region]["coordinates"][3]), 
                color_rank[region], 
                5,
            )

    cv2.imwrite(
        os.path.join(output_dir_path, f"complete_image.jpeg"),
        image
    )

    
    # pre_processed = pre_process_image(img, pre_file)
    # text_boxes = find_text_boxes(pre_processed)
    # cells = find_table_in_boxes(text_boxes)
    # hor_lines, ver_lines = build_lines(cells)

    # # Visualize the result
    # vis = img.copy()

    # # for box in text_boxes:
    # #     (x, y, w, h) = box
    # #     cv2.rectangle(vis, (x, y), (x + w - 2, y + h - 2), (0, 255, 0), 1)

    # for line in hor_lines:
    #     [x1, y1, x2, y2] = line
    #     cv2.line(vis, (x1, y1), (x2, y2), (255, 0, 0), 5)

    # for line in ver_lines:
    #     [x1, y1, x2, y2] = line
    #     cv2.line(vis, (x1, y1), (x2, y2), (0, 0, 255), 5)

    # cv2.imwrite(out_file, vis)