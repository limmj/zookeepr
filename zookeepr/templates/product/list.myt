<h2>List products</h2>

% if len(c.product_categories) > 0:
%   for category in c.product_categories:
<h3><% category.name %></h3>
<table>
  <tr>
    <th>Active</th>
    <th>Description</th>
    <th>Cost</th>
    <th>&nbsp;</th>
    <th>&nbsp;</th>
  </tr>
%       if len(category.products) > 0:
%           for product in category.products:
<tr>
  <td><% product.active %></td>
  <td><% h.link_to(product.description, url=h.url(action='view', id=product.id)) %></td>
  <td>$<% product.cost %></td>
%               if c.can_edit:
%                   for action in ['edit', 'delete']:
  <td><% h.link_to(action, url=h.url(action=action, id=product.id)) %></td>
%                   #endfor
%               #endif
</tr>
%           #endfor
%       #endif
</table>
%   #endfor
% #endif


<%python>
#if c.product_pages.current.previous:
#    m.write(h.link_to('Previous page', url=h.url(page=c.product_pages.current.previous)) + '  ')
#if c.product_pages.current.next:
#    m.write(h.link_to('Next page', url=h.url(page=c.product_pages.current.next)))

if c.can_edit:
    m.write('<p>' + h.link_to('New product', url=h.url(action='new')) + '</p>')
</%python>
 
