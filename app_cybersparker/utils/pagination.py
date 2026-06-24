from django.utils.safestring import mark_safe


class Pagination(object):
    def __init__(self, request, queryset, page_size=10, page_param="page", plus=1, rows_per_page_options=[10, 15, 20, 50, 100, 200, 500,1000,5000]):
        import copy
        query_dict = copy.deepcopy(request.GET)
        query_dict._mutable = True
        self.query_dict = query_dict
        
        self.page_param = page_param
        page = request.GET.get(page_param, "1")
        if page.isdecimal():
            page = int(page)
        else:
            page = 1
        
        self.page = page
        
        requested_page_size = int(request.GET.get("rows_per_page", page_size))
        if requested_page_size in rows_per_page_options:
            self.page_size = requested_page_size
        else:
            self.page_size = page_size
        
        self.start = (page - 1) * self.page_size
        self.end = page * self.page_size
        
        self.page_queryset = queryset[self.start:self.end]
        
        total_count = queryset.count()
        self.total_count = total_count
        total_page_count, div = divmod(total_count, self.page_size)
        if div:
            total_page_count += 1
        self.total_page_count = total_page_count
        self.plus = plus
        self.rows_per_page_options = rows_per_page_options
    
    def html(self):
        if self.total_page_count <= 2 * self.plus + 1:
            start_page = 1
            end_page = self.total_page_count
        else:
            if self.page <= self.plus:
                start_page = 1
                end_page = 2 * self.plus + 1
            else:
                if (self.page + self.plus) > self.total_page_count:
                    start_page = self.total_page_count - 2 * self.plus
                    end_page = self.total_page_count
                else:
                    start_page = self.page - self.plus
                    end_page = self.page + self.plus
        
        page_str_list = []
        
        self.query_dict.setlist(self.page_param, [1])
        page_str_list.append('<li><a href="?{}" style="border-radius: 0; background-color:#fff;color:#3498db ;height:27.7px;">first</a></li>'.format(self.query_dict.urlencode()))
        
        if self.page > 1:
            self.query_dict.setlist(self.page_param, [self.page - 1])
            prev = '<li><a href="?{}"><</a></li>'.format(self.query_dict.urlencode())
        else:
            self.query_dict.setlist(self.page_param, [1])
            prev = '<li><a href="?{}"><</a></li>'.format(self.query_dict.urlencode())
        page_str_list.append(prev)
        
        for i in range(start_page, end_page + 1):
            self.query_dict.setlist(self.page_param, [i])
            if i == self.page:
                ele = '<li class="active blue-button"><a href="?{}">{}</a></li>'.format(self.query_dict.urlencode(), i)
            else:
                ele = '<li><a href="?{}">{}</a></li>'.format(self.query_dict.urlencode(), i)
            page_str_list.append(ele)
        
        if self.page < self.total_page_count:
            self.query_dict.setlist(self.page_param, [self.page + 1])
            prev = '<li><a href="?{}">></a></li>'.format(self.query_dict.urlencode())
        else:
            self.query_dict.setlist(self.page_param, [self.total_page_count])
            prev = '<li><a href="?{}">></a></li>'.format(self.query_dict.urlencode())
        page_str_list.append(prev)
        
        self.query_dict.setlist(self.page_param, [self.total_page_count])
        page_str_list.append('<li><a href="?{}" style="border-radius: 0; background-color:#fff;color:#3498db ;height:27.6px;">last</a></li>'.format(self.query_dict.urlencode()))
        
        search_string = '''
            <li>
               <form style="float: left; margin-left: -1px; display: flex; align-items: center;" method="get">
                <input name="page" style="position: relative; float: left; display: inline-block; width: 60px; height: 27.6px;  padding: 0; border-radius: 0; margin-right: 5px;margin-left: 5px;" type="text" class="form-control" placeholder="">
                <button style="border-radius: 0; background-color: #fff; color: #3498db; height: 29px; display: flex; align-items: center; " class="btn btn-default" type="submit">
                    <strong>jump</strong>
                </button>
                <span style="font-weight: normal;">&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;per page</span>
                <select name="rows_per_page" onchange="this.form.submit()" style="border-radius: 0; background-color: #fff; color: #3498db; height: 29px; border: 1px solid #e7e7e7;">
                    {}
                </select>
            </form>
            </li>
        '''.format(''.join(['<option value="{}"{}>{}</option>'.format(option, ' selected' if self.page_size == option else '', option) for option in self.rows_per_page_options]))
        page_str_list.append(search_string)
        
        page_str_list.append('<div style="display: flex; align-items: center; justify-content: center; height: 28px; margin-left:10px;"><span style="font-weight:normal;"> all {} pages |  total <strong>{}</strong> records</span></div>'.format( self.total_page_count,self.total_count))
        page_string = mark_safe("".join(page_str_list))
        
        return page_string
        