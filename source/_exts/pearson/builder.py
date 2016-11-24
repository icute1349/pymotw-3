# -*- coding: utf-8 -*-
"""LaTeX builder using Pearson style templates.
"""

import os
from os import path
import textwrap
import warnings

from six import iteritems
from docutils import nodes
from docutils.io import FileOutput
from docutils.utils import new_document
from docutils.frontend import OptionParser

from sphinx import highlighting
from sphinx import package_dir, addnodes
from sphinx.builders import Builder
from sphinx.environment import NoUri
from sphinx.errors import SphinxError
from sphinx.locale import _
from sphinx.theming import Theme
from sphinx.util import copy_static_entry
from sphinx.util import texescape
from sphinx.util.console import bold, darkgreen
from sphinx.util.nodes import inline_all_toctrees
from sphinx.util.osutil import SEP, copyfile

from pearson import writer


_package_dir = path.abspath(path.dirname(__file__))


class PearsonLaTeXBuilder(Builder):
    """
    Builds LaTeX output to create PDF.
    """
    name = 'pearson'
    format = 'latex'
    supported_image_types = ['application/pdf', 'image/png', 'image/jpeg']
    usepackages = []

    # Modified by init_templates()
    theme = None

    def init(self):
        self.info('loading builder from Pearson extension')
        self.docnames = []
        self.document_data = []
        self.init_templates()
        texescape.init()
        self.check_options()

    def check_options(self):
        if self.config.latex_toplevel_sectioning not in (None, 'part', 'chapter', 'section'):
            self.warn('invalid latex_toplevel_sectioning, ignored: %s' %
                      self.config.latex_top_sectionlevel)
            self.config.latex_top_sectionlevel = None

        if self.config.latex_use_parts:
            warnings.warn('latex_use_parts will be removed at Sphinx-1.5. '
                          'Use latex_toplevel_sectioning instead.',
                          DeprecationWarning)

            if self.config.latex_toplevel_sectioning:
                self.warn('latex_use_parts conflicts with latex_toplevel_sectioning, ignored.')

    def get_outdated_docs(self):
        return 'all documents'  # for now

    def get_target_uri(self, docname, typ=None):
        if docname not in self.docnames:
            raise NoUri
        else:
            return '%' + docname

    def get_relative_uri(self, from_, to, typ=None):
        # ignore source path
        return self.get_target_uri(to, typ)

    def get_theme_config(self):
        return self.config.pearson_theme, self.config.pearson_theme_options

    def init_templates(self):
        Theme.init_themes(
            self.confdir,
            [path.join(_package_dir, 'themes')] + self.config.pearson_theme_path,
            warn=self.warn,
        )
        themename, themeoptions = self.get_theme_config()
        self.theme = Theme(themename, warn=self.warn)
        self.theme_options = themeoptions.copy()
        self.create_template_bridge()
        self.templates.init(self, self.theme)

    def init_chapters(self):
        chapters = list(self.config.pearson_chapters)
        if not chapters:
            self.warn('no "pearson_chapters" config value found; no documents '
                      'will be written')
            return

        for chap in chapters:
            if chap not in self.env.all_docs:
                self.warn('"pearson_chapters" config value references unknown '
                          'document %s' % chap)
                continue
            self.document_data.append(chap)

    def _render_template(self, template_name, file_name, context):
        self.info('writing {}'.format(file_name))
        output = FileOutput(
            destination_path=file_name,
            encoding='utf-8',
        )
        try:
            body = self.templates.render(template_name, context)
        except Exception as err:
            self.info(bold('Failed to render template {}: {} at {}'.format(
                template_name, err, err.lineno))
            )
            raise
        output.write(body)
        return body

    def _write_pygments_stylesheet(self, file_name):
        self.info('writing {}'.format(file_name))
        output = FileOutput(
            destination_path=file_name,
            encoding='utf-8',
        )
        highlighter = highlighting.PygmentsBridge(
            'latex',
            self.config.pygments_style, self.config.trim_doctest_flags)
        body = textwrap.dedent('''
        %% generated by Pearson extension for Sphinx
        %%
        %% These are the code syntax-highlighting directives
        %% produced by pygments using the theme for the
        %% document
        %%
        ''') + highlighter.get_stylesheet()

        output.write(body)
        return body

    def write(self, *ignored):
        docwriter = writer.PearsonLaTeXWriter(self)
        docsettings = OptionParser(
            defaults=self.env.settings,
            components=(docwriter,),
            read_config_files=True).get_default_values()

        self.init_chapters()

        self._write_pygments_stylesheet(
            path.join(self.outdir, 'pygments.sty'),
        )

        # Build up a context object for the templates.
        global_context = {
            'title': self.config.pearson_title,
            'subtitle': self.config.pearson_subtitle,
            'author': self.config.pearson_author,
            'chapter_names': [],
            'appendices': [],
        }

        self._render_template(
            'half-title.tex',
            path.join(self.outdir, 'half-title.tex'),
            global_context,
        )
        self._render_template(
            'title.tex',
            path.join(self.outdir, 'title.tex'),
            global_context,
        )

        def process_doc(name_fmt, num, docname):
            name = name_fmt.format(num)
            destination = FileOutput(
                destination_path=path.join(self.outdir, name + '.tex'),
                encoding='utf-8')
            self.info('writing {} to {}.tex ... '.format(docname, name), nonl=1)
            toctrees = self.env.get_doctree(docname).traverse(addnodes.toctree)
            if toctrees:
                if toctrees[0].get('maxdepth') > 0:
                    tocdepth = toctrees[0].get('maxdepth')
                else:
                    tocdepth = None
            else:
                tocdepth = None
            doctree = self.assemble_doctree(
                docname,
                False,  # toctree_only
                appendices=[],
            )
            doctree['tocdepth'] = tocdepth
            self.post_process_images(doctree)
            doctree.settings = docsettings
            # doctree.settings.author = author
            # doctree.settings.title = title
            doctree.settings.contentsname = self.get_contentsname(docname)
            doctree.settings.docname = docname
            # doctree.settings.docclass = docclass
            docwriter.write(doctree, destination)
            self.info("done")
            return name

        # First generate the chapters
        chap_name_fmt = 'chap{:02d}'
        if len(self.document_data) >= 100:
            chap_name_fmt = 'chap{:03d}'

        for chap_num, docname in enumerate(self.document_data, 1):
            name = process_doc(chap_name_fmt, chap_num, docname)
            global_context['chapter_names'].append(name)

        # Then any appendices
        app_name_fmt = 'app{:02d}'
        if len(self.config.latex_appendices) >= 100:
            app_name_fmt = 'app{:03d}'

        for app_num, docname in enumerate(self.config.latex_appendices, 1):
            name = process_doc(app_name_fmt, app_num, docname)
            global_context['appendices'].append(name)

        # Finally the main book template
        global_context['external_docs'] = (
            global_context['chapter_names'] +
            global_context['appendices']
        )
        self._render_template(
            'book.tex',
            path.join(self.outdir, 'book.tex'),
            global_context,
        )

    def get_contentsname(self, indexfile):
        tree = self.env.get_doctree(indexfile)
        contentsname = None
        for toctree in tree.traverse(addnodes.toctree):
            if 'caption' in toctree:
                contentsname = toctree['caption']
                break

        return contentsname

    def assemble_doctree(self, indexfile, toctree_only, appendices):
        self.docnames = set([indexfile] + appendices)
        self.info(darkgreen(indexfile) + " ", nonl=1)
        tree = self.env.get_doctree(indexfile)
        tree['docname'] = indexfile
        if toctree_only:
            # extract toctree nodes from the tree and put them in a
            # fresh document
            new_tree = new_document('<latex output>')
            new_sect = nodes.section()
            new_sect += nodes.title(u'<Set title in conf.py>',
                                    u'<Set title in conf.py>')
            new_tree += new_sect
            for node in tree.traverse(addnodes.toctree):
                new_sect += node
            tree = new_tree
        largetree = inline_all_toctrees(self, self.docnames, indexfile, tree,
                                        darkgreen, [indexfile])
        largetree['docname'] = indexfile
        for docname in appendices:
            appendix = self.env.get_doctree(docname)
            appendix['docname'] = docname
            largetree.append(appendix)
        self.info()
        self.info("resolving references...")
        self.env.resolve_references(largetree, indexfile, self)
        # resolve :ref:s to distant tex files -- we can't add a cross-reference,
        # but append the document name
        for pendingnode in largetree.traverse(addnodes.pending_xref):
            docname = pendingnode['refdocname']
            sectname = pendingnode['refsectname']
            newnodes = [nodes.emphasis(sectname, sectname)]
            for subdir, title in self.titles:
                if docname.startswith(subdir):
                    newnodes.append(nodes.Text(_(' (in '), _(' (in ')))
                    newnodes.append(nodes.emphasis(title, title))
                    newnodes.append(nodes.Text(')', ')'))
                    break
            else:
                pass
            pendingnode.replace_self(newnodes)
        return largetree

    def finish(self):
        # copy image files
        if self.images:
            self.info(bold('copying images...'), nonl=1)
            for src, dest in iteritems(self.images):
                self.info(' '+src, nonl=1)
                copyfile(path.join(self.srcdir, src),
                         path.join(self.outdir, dest))
            self.info()

        # copy TeX support files from texinputs
        # self.info(bold('copying TeX support files...'))
        # staticdirname = path.join(package_dir, 'texinputs')
        # for filename in os.listdir(staticdirname):
        #     if not filename.startswith('.'):
        #         self.info(' ' + filename, nonl=1)
        #         copyfile(path.join(staticdirname, filename),
        #                  path.join(self.outdir, filename))

        # copy additional files
        if self.config.latex_additional_files:
            self.info(bold('copying additional files...'), nonl=1)
            for filename in self.config.latex_additional_files:
                self.info(' '+filename, nonl=1)
                copyfile(path.join(self.confdir, filename),
                         path.join(self.outdir, path.basename(filename)))
            self.info()

        # the logo is handled differently
        if self.config.latex_logo:
            logobase = path.basename(self.config.latex_logo)
            logotarget = path.join(self.outdir, logobase)
            if not path.isfile(path.join(self.confdir, self.config.latex_logo)):
                raise SphinxError('logo file %r does not exist' % self.config.latex_logo)
            elif not path.isfile(logotarget):
                copyfile(path.join(self.confdir, self.config.latex_logo), logotarget)

        # finally, copy over theme-supplied static files, some of which
        # might override the files copied earlier
        if self.theme:
            self.info(bold('copying static files...'), nonl=1)
            ctx = {}
            themeentries = [path.join(themepath, 'static')
                            for themepath in self.theme.get_dirchain()[::-1]]
            for entry in themeentries:
                self.info(' ' + entry)
                copy_static_entry(entry, self.outdir,
                                  self, ctx)

        self.info('done')

    def cleanup(self):
        # clean up theme stuff
        if self.theme:
            self.theme.cleanup()
