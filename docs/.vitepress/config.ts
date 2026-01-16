import { defineConfig } from 'vitepress'

export default defineConfig({
  title: 'YAAY',
  description: 'Yet Another Agentic System',
  
  // For GitHub Pages deployment to /yaay/
  base: '/yaay/',
  
  head: [
    ['link', { rel: 'icon', type: 'image/svg+xml', href: '/yaay/logo.svg' }]
  ],

  // Ignore dead links for external references
  ignoreDeadLinks: true,

  themeConfig: {
    logo: '/logo.svg',
    siteTitle: 'YAAY',
    
    nav: [
      { text: 'Guide', link: '/getting-started/quickstart' },
      { text: 'Operator', link: '/operator/overview' },
      { text: 'Python', link: '/python-framework/overview' },
      { text: 'GitHub', link: 'https://github.com/axsaucedo/yaay' }
    ],

    sidebar: [
      {
        text: 'Getting Started',
        items: [
          { text: 'Quick Start', link: '/getting-started/quickstart' },
          { text: 'Installation', link: '/getting-started/installation' },
          { text: 'Concepts', link: '/getting-started/concepts' }
        ]
      },
      {
        text: 'Kubernetes Operator',
        items: [
          { text: 'Overview', link: '/operator/overview' },
          { text: 'Agent CRD', link: '/operator/agent-crd' },
          { text: 'ModelAPI CRD', link: '/operator/modelapi-crd' },
          { text: 'MCPServer CRD', link: '/operator/mcpserver-crd' },
          { text: 'Gateway API', link: '/operator/gateway-api' }
        ]
      },
      {
        text: 'Python Framework',
        items: [
          { text: 'Overview', link: '/python-framework/overview' },
          { text: 'Agent', link: '/python-framework/agent' },
          { text: 'Agentic Loop', link: '/python-framework/agentic-loop' },
          { text: 'MCP Tools', link: '/python-framework/mcp-tools' },
          { text: 'Model API', link: '/python-framework/model-api' },
          { text: 'Server', link: '/python-framework/server' }
        ]
      },
      {
        text: 'Tutorials',
        items: [
          { text: 'Simple Agent', link: '/tutorials/simple-agent-tools' },
          { text: 'Multi-Agent', link: '/tutorials/multi-agent' },
          { text: 'Custom Tools', link: '/tutorials/custom-mcp-tools' }
        ]
      },
      {
        text: 'Reference',
        items: [
          { text: 'Environment Variables', link: '/reference/environment-variables' },
          { text: 'Troubleshooting', link: '/reference/troubleshooting' }
        ]
      },
      {
        text: 'Development',
        items: [
          { text: 'Testing', link: '/development/testing' }
        ]
      }
    ],

    socialLinks: [
      { icon: 'github', link: 'https://github.com/axsaucedo/yaay' }
    ],

    footer: {
      message: 'Released under the Apache 2.0 License.',
      copyright: 'Copyright © 2024-present YAAY Contributors'
    },

    search: {
      provider: 'local'
    },

    editLink: {
      pattern: 'https://github.com/axsaucedo/yaay/edit/main/docs/:path',
      text: 'Edit this page on GitHub'
    }
  }
})
