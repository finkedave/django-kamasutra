import datetime
from django.db import models
from django.db.models import Count, F, Q
from django.utils.translation import ugettext as _
from django.contrib.contenttypes import generic
from django.contrib.contenttypes.models import ContentType
from django.template.loader import select_template, render_to_string
from django.template import Context, RequestContext

from positions import settings

class PositionManager(models.Manager):
    
    def add_object(self, position, obj, order=1):
        """
        Add an object to a position.
        """
        # check to make sure position is within the position count.
        if not order in range(1, position.count+1):
            order = 1

        # Retrieve the content type for the supplied object.
        ctype = ContentType.objects.get_for_model(obj)
        
        # Ensure that the position allows the object.
        if not self.is_applicable(position, obj):
            return False
        
        # Create the new PositionContent object, force uniquness.
        try:
            PositionContent._default_manager.get(position__pk=position.pk, 
                content_type__pk=ctype.pk, object_id=str(obj.id))
            return False
        except PositionContent.DoesNotExist:
            new_obj = PositionContent._default_manager.create(
                position=position, content_type=ctype, object_id=obj.pk, 
                order=order, add_date=datetime.datetime.now())
            
        # Adjust the order of each item
        PositionContent.objects.reorder(position, new_obj, is_removed=False)
        
        # Remove extra items
        PositionContent.objects.prune(position)
        
        return True
            
    def remove_object(self, position, obj):
        """
        Remove an object from a position.
        """
        # Retrieve the content type for the supplied object.
        ctype = ContentType.objects.get_for_model(obj)
        try:
            item = PositionContent._default_manager.get(position=position, 
                content_type=ctype, object_id=str(obj.pk))
        except PositionContent.DoesNotExist:
            return False
            
        # Adjust the order of each item
        PositionContent.objects.reorder(position, item, is_removed=True)
        item.delete()
        
        return True
    
    def get_content_old(self, position, count=None, as_contenttype=True):
        """
        Gets the content for the position given.
        """
        if not isinstance(position, Position):
            return []
        
        # Get the number of items that are going to be returned.
        num = position.count
        if isinstance(count, int) and count > 0:
            num = count
        
        # Get the items
        items = PositionContent._default_manager.filter(
            position=position).order_by('order')[:num]
            
        # If supplied, return the content objects for each item.
        if as_contenttype:
            items = [item.content_object for item in items if item.content_object]
        
        return items
    
    def get_content(self, position, count=None, as_contenttype=True):
        if isinstance(position, basestring):
            items = PositionContent._default_manager.filter(
                position__name__iexact=position).select_related().order_by('order')
        elif isinstance(position, Position):
            items = PositionContent._default_manager.filter(
                position=position).select_related().order_by('order')
        
        if count:
            items = items[:count]
            
    def contains_object(self, position, obj):
        """
        Check if position contains object.
        """
        ctype = ContentType.objects.get_for_model(obj)
        
        try:
            position.positioncontent_set.get(
                content_type__pk=ctype.pk, 
                object_id=str(obj.pk))
        except PositionContent.DoesNotExist:
            return False
            
        return True
        
    def positions_for_object(self, obj):
        """
        Gets all the positions the supplied object is part of
        """
        if not obj:
            return []
            
        ctype = ContentType.objects.get_for_model(obj)
        
        return Position.objects.filter(
            positioncontent__content_type__pk=ctype.pk, 
            positioncontent__object_id=str(obj.pk)).distinct()

        
    def get_applicable(self, obj, return_all=False):
        """
        Gets the positions that the object can be assigned.
        """
        ctype = ContentType.objects.get_for_model(obj)
            
        if return_all:
            positions = self.filter(
                Q(eligible_types__in=[ctype,]) | Q(allow_all_types=True))
        else:
            positions = self.filter(
                Q(eligible_types__in=[ctype,]) | Q(allow_all_types=True)).exclude(
                    positioncontent__content_type=ctype, 
                    positioncontent__object_id=str(obj.pk))
                    
        return positions
        
    def is_applicable(self, position, obj):
        """
        Check to make sure object can be assigned to a position.
        """
        if position.allow_all_types:
            return True
        
        ctype = ContentType.objects.get_for_model(obj)
        items = self.filter(pk=position.pk, 
            eligible_types__in=[ctype,]).count()
            
        if items:
            return True
        return False
        
    def can_be_positioned(self, obj):
        """
        Check to see if any positions can position the supplied object.
        """
        ctype = ContentType.objects.get_for_model(obj)
        
        items = self.filter(
            Q(eligible_types__in=[ctype,]) | Q(allow_all_types=True))
            
        if items:
            return True
        return False
        

class Position(models.Model):
    name = models.SlugField(_('Name (slug)'), unique=True,
        help_text=_('Name of the location, must only contain alpha numeric characters.'))
    count = models.PositiveIntegerField(_('Count'), default=1,
        help_text=_('The number of items to return when getting the content.'))
    eligible_types = models.ManyToManyField(ContentType, 
        verbose_name=_('Eligible Types'), null=True, blank=True, 
        help_text=_('The types of content that this Position can contain. This is ingored if allow_all_types is True.'))
    allow_all_types = models.BooleanField(_('Allow all Content Types'), 
        default=False, 
        help_text=_('Select this check box if this position should allow all types of content.'))
    description = models.TextField(_('Description'), blank=True)
    
    objects = PositionManager()
    
    class Meta:
        ordering = ['name']
    
    def __unicode__(self):
        return self.name
        
        
class PositionContentManager(models.Manager):
        
    def prune(self, position):
        """
        Trim the amount of items in the position.
        """
        # Get all the items in the correct order.
        items = self.filter(position=position).order_by('order')
        
        # If the total of items is greater than the position count plus the 
        # CONTENT_OVERLAP_COUNT, retrieve the excess items and delete them
        if len(items) > position.count + settings.CONTENT_OVERLAP_COUNT:
            
            # Retrieve all the ids of PositionContent after the 
            # position.count + CONTENT_OVERMAP_COUNT
            ids = [i.pk for i in items[(position.count + settings.CONTENT_OVERLAP_COUNT):]]
            
            # Remove, if any, the items left over.
            if ids:
                self.filter(pk__in=ids).delete()
                
        
    def reorder(self, position, existing_item, is_removed=False):
        """
        Reorder the content after a new content object is removed or added.
        """
        for item in self.filter(position=position).order_by('order'):
            # Only update the item order if it is not the supplied item.
            if item != existing_item:
                
                # Add 1 to all items after the supplied new item, which 
                # should always be the first item or subtract 1 for items 
                # after the supplied item if the item is marked for removal.
                if is_removed:
                    if item.order > existing_item.order:
                        item.order -= 1
                else:
                    if item.order >= existing_item.order:
                        item.order += 1
                
                item.save()

                                                                                                                                                                          
class PositionContent(models.Model):
    """
    Position Content
    """
    position = models.ForeignKey(Position, verbose_name=_('Position'), 
        help_text=_('The position where this object will be shown.'))
    content_type = models.ForeignKey(ContentType, verbose_name=_('Content Type.'),
        help_text=_('Type of this object.'))
    object_id = models.CharField(_('Object ID'), max_length=255, 
        help_text=_('The ID/PK of the object.'))
    content_object = generic.GenericForeignKey('content_type', 'object_id')
    order = models.PositiveIntegerField(_('Order'), default=1,
        help_text=_('The order of the object.'))
    add_date = models.DateTimeField(_('Date Added'), default=datetime.datetime.now)
    
    objects = PositionContentManager()
    
    class Meta:
        ordering = ['position__name', 'order', '-add_date']
    
    def render(self, template=None, suffix=None, extra_context={}, context_instance=None):
        """
        Render the content using template search in the following order:
        
        1. Passed template
        2. positions/render/<position>/<app>__<model>__<suffix>.html
        3. positions/render/<position>/<app>__<model>.html
        4. POSITION_TEMPLATES setting for content type or 
           positions/render/<app>__<model>.html
        5. positions/render/default.html
        """
        t, model, app = None, "", ""
        
        model = self.content_type.model.lower()
        app = self.content_type.app_label.lower()
        pos_tmpl_path = 'positions/render/%s/' % self.position.name
        
        template_list = []
        if template:
            template_list.append(template)
        if suffix:
            tmpl_name = '%s__%s__%s.html' % (app, model, suffix)
            template_list.append("".join([pos_tmpl_path, tmpl_name]))
            
        tmpl_name = '%s__%s.html' % (app, model)
        template_list.append("".join([pos_tmpl_path, tmpl_name]))
        
        tmpl_name = 'positions/render/%s' % tmpl_name
        template_list.append(
            settings.TEMPLATES.get('%s.%s' % (app, model), tmpl_name))
        
        tmpl_name = "default.html"
        template_list.append("".join([pos_tmpl_path, tmpl_name]))
        template_list.append('positions/render/default.html')
        
        t = select_template(template_list)
        if not t: return None
        
        context = Context()
        if context_instance and isinstance(context_instance, RequestContext):
            context.update(context_instance.__dict__)
            
        context.update({'obj': self.content_object, 'content': self})
        context.update(extra_context)
        
        return t.render(context)
    
    def __unicode__(self):
        return '%s - %s' % (self.position.name, self.content_object)