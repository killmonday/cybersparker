# custom_tags.py

from django import template

register = template.Library()

@register.filter(name='non_verify')
def non_verify(function_list):
    for value in function_list:
        if value != 1:  #verify
            return True
    return False

@register.filter(name='split_newlines')
def split_newlines(value):
    product_list =  value.split('\n')
    # print("*********",product_list)
    return  product_list