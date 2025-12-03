"""
Blog Management Endpoints
CRUD operations for blog posts
"""
import re
import html
from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, HTTPException, Depends, Query, status
from pydantic import BaseModel, Field, validator
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import desc, or_, and_, select

from src.auth import get_admin_user, get_current_user
from src.database import get_async_db
from src.database.models import BlogPost, User
from src.utils.logger import setup_logger
from src.utils.config import load_config
from src.ai.llm_factory import LLMFactory

logger = setup_logger(__name__)
router = APIRouter(prefix="/blog", tags=["blog"])

# Allowed blog categories with descriptions
ALLOWED_CATEGORIES = [
    "Product",
    "Productivity",
    "Education & AI",
    "Business",
    "Engineering"
]

# Category descriptions and content guidance
CATEGORY_DESCRIPTIONS = {
    "Product": {
        "description": "Product updates, feature announcements, roadmap, and release notes",
        "content_types": [
            "Feature announcements and releases",
            "Product roadmap and vision",
            "New capabilities (Gmail extension, voice interface, etc.)",
            "Release notes and changelogs",
            "Product updates and improvements"
        ]
    },
    "Productivity": {
        "description": "Tips, workflows, strategies, and techniques for maximizing productivity",
        "content_types": [
            "Email management tips and workflows",
            "Calendar optimization strategies",
            "Task automation techniques",
            "Time management best practices",
            "Multi-step workflow examples",
            "Efficiency hacks and shortcuts"
        ]
    },
    "Education & AI": {
        "description": "Tutorials, guides, AI concepts, and educational content about how Clavr works",
        "content_types": [
            "Getting started guides and tutorials",
            "How Clavr works (RAG, semantic search, autonomous agents)",
            "AI concepts and explanations",
            "Best practices and advanced techniques",
            "Step-by-step walkthroughs",
            "Understanding LangGraph and orchestration"
        ]
    },
    "Business": {
        "description": "ROI, case studies, enterprise value, and business impact",
        "content_types": [
            "ROI calculations and business value",
            "Case studies and success stories",
            "Enterprise use cases",
            "Team productivity metrics",
            "Cost savings and efficiency gains",
            "Business transformation stories"
        ]
    },
    "Engineering": {
        "description": "Technical architecture, API documentation, implementation details, and system design",
        "content_types": [
            "Technical architecture deep-dives",
            "API documentation and guides",
            "Implementation details and code examples",
            "Performance optimization",
            "System design and scalability",
            "Technical best practices"
        ]
    }
}


# ============================================
# UTILITY FUNCTIONS
# ============================================

def normalize_rich_text_content(content: str) -> str:
    """
    Normalize and prepare rich text content from frontend editors
    
    Handles:
    - HTML content from WYSIWYG editors
    - Markdown content from markdown editors
    - Preserves formatting while ensuring safe storage
    - Normalizes whitespace and line breaks
    
    Args:
        content: Raw content from frontend editor (HTML or Markdown)
        
    Returns:
        Normalized content string ready for storage
    """
    if not content:
        return ""
    
    # Preserve the content as-is (frontend is responsible for sanitization)
    # We just normalize whitespace at the edges
    content = content.strip()
    
    # Ensure content ends with a newline if it's markdown (helps with rendering)
    # But don't modify HTML content
    if content and not content.startswith('<'):
        # Likely markdown - ensure proper line breaks
        if not content.endswith('\n'):
            content += '\n'
    
    return content


def detect_content_format(content: str) -> str:
    """
    Detect whether content is HTML or Markdown
    
    Args:
        content: Content string to analyze
        
    Returns:
        'html' or 'markdown'
    """
    if not content:
        return 'markdown'
    
    # Simple heuristic: if content starts with HTML tags, it's HTML
    # More sophisticated detection could be added later
    content_stripped = content.strip()
    
    # Check for common HTML patterns
    html_patterns = [
        r'^<[a-z][\s>]',  # Opening tag
        r'<div',  # Common HTML elements
        r'<p>',
        r'<h[1-6]',
        r'<ul',
        r'<ol',
        r'<li',
        r'<strong',
        r'<em',
        r'<a\s+href',
        r'<img',
        r'<code',
        r'<pre',
        r'<blockquote',
    ]
    
    for pattern in html_patterns:
        if re.search(pattern, content_stripped, re.IGNORECASE):
            return 'html'
    
    # Check for markdown patterns
    markdown_patterns = [
        r'^#{1,6}\s+',  # Headers
        r'\*\*.*?\*\*',  # Bold
        r'\*.*?\*',  # Italic
        r'\[.*?\]\(.*?\)',  # Links
        r'```',  # Code blocks
        r'^\s*[-*+]\s+',  # Lists
        r'^\s*\d+\.\s+',  # Numbered lists
    ]
    
    for pattern in markdown_patterns:
        if re.search(pattern, content_stripped, re.MULTILINE):
            return 'markdown'
    
    # Default to markdown if unclear
    return 'markdown'


def generate_slug(title: str) -> str:
    """Generate URL-friendly slug from title"""
    # Convert to lowercase
    slug = title.lower()
    # Replace spaces and special characters with hyphens
    slug = re.sub(r'[^\w\s-]', '', slug)
    slug = re.sub(r'[-\s]+', '-', slug)
    # Remove leading/trailing hyphens
    slug = slug.strip('-')
    return slug


def calculate_read_time(content: str) -> int:
    """
    Calculate estimated read time in minutes for average avid readers
    
    Uses 300 words per minute (WPM) as the reading speed for avid readers.
    This is more accurate than the standard 200 WPM for average readers.
    
    Strips markdown and HTML tags to get accurate word count.
    Handles:
    - Markdown: **bold**, *italic*, `code`, # headings, - lists, etc.
    - HTML: <tags>, &entities;
    
    Research shows:
    - Average reader: 200-250 WPM
    - Avid reader: 300-400 WPM
    - Speed reader: 500+ WPM
    
    We use 300 WPM as a good middle ground for avid readers.
    """
    import re
    
    # Remove HTML tags
    text = re.sub(r'<[^>]+>', '', content)
    
    # Remove markdown formatting
    # Remove code blocks (```code```)
    text = re.sub(r'```[\s\S]*?```', '', text)
    # Remove inline code (`code`)
    text = re.sub(r'`[^`]+`', '', text)
    # Remove markdown links [text](url)
    text = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', text)
    # Remove markdown images ![alt](url)
    text = re.sub(r'!\[([^\]]*)\]\([^\)]+\)', '', text)
    # Remove markdown headers (# ## ###)
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
    # Remove markdown bold/italic (**text**, *text*)
    text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)
    text = re.sub(r'\*([^*]+)\*', r'\1', text)
    # Remove markdown list markers (-, *, +, 1., etc.)
    text = re.sub(r'^[\s]*[-*+]\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'^\s*\d+\.\s+', '', text, flags=re.MULTILINE)
    # Remove markdown blockquotes (>)
    text = re.sub(r'^>\s+', '', text, flags=re.MULTILINE)
    # Remove HTML entities
    text = re.sub(r'&[a-zA-Z]+;', '', text)
    text = re.sub(r'&#\d+;', '', text)
    
    # Clean up whitespace
    text = re.sub(r'\s+', ' ', text)
    text = text.strip()
    
    # Count words
    words = len(text.split()) if text else 0
    
    # Use 300 WPM for avid readers (more accurate than 200 WPM)
    # Round to nearest minute, minimum 1 minute
    minutes = max(1, round(words / 300))
    return minutes


# ============================================
# REQUEST/RESPONSE MODELS
# ============================================

class BlogPostBase(BaseModel):
    """
    Base blog post schema
    
    Supports rich content formatting:
    - **Markdown**: Headings (# ## ###), bold (**text**), italic (*text*), 
      lists (-, *, 1.), code blocks (```code```), links [text](url)
    - **HTML**: Full HTML support for complex formatting
    
    The `description` field serves as the subtitle/lead paragraph shown below the title.
    The `content` field contains the full blog post body with all formatting.
    """
    title: str = Field(..., min_length=1, max_length=500, description="Main blog post title")
    description: Optional[str] = Field(None, description="Subtitle/lead paragraph shown below title")
    content: str = Field(
        ..., 
        min_length=1, 
        description="Full blog post content in rich text format (HTML or Markdown). "
                   "Supports: headings (H1-H6), bold, italic, underline, strikethrough, "
                   "lists (ordered/unordered), links, code blocks, blockquotes, images, "
                   "and all standard HTML/Markdown formatting. Content is stored as-is from the editor."
    )
    category: str = Field(
        ..., 
        min_length=1, 
        max_length=100, 
        description="Category tag. Must be one of: Product (updates/features), Productivity (tips/workflows), Education & AI (tutorials/concepts), Business (ROI/case studies), Engineering (technical/API). See /blog/categories/info for details."
    )
    featured_image_url: Optional[str] = Field(None, description="URL to featured image")
    meta_title: Optional[str] = Field(None, max_length=500, description="SEO title (can differ from display title)")
    meta_description: Optional[str] = Field(None, description="SEO meta description")
    tags: Optional[List[str]] = Field([], description="List of tags for categorization")
    
    @validator('content')
    def validate_content(cls, v):
        """Normalize and validate rich text content"""
        if not v or not v.strip():
            raise ValueError("Content cannot be empty")
        return normalize_rich_text_content(v)
    
    @validator('category')
    def validate_category(cls, v):
        """Ensure category is one of the allowed categories"""
        if v not in ALLOWED_CATEGORIES:
            raise ValueError(f"Category must be one of: {', '.join(ALLOWED_CATEGORIES)}")
        return v
    
    @validator('tags')
    def validate_tags(cls, v):
        """Ensure tags is a list"""
        return v if v is not None else []


class BlogPostCreate(BlogPostBase):
    """Schema for creating a blog post"""
    slug: Optional[str] = None  # Auto-generated if not provided
    is_published: bool = False
    published_at: Optional[datetime] = None
    
    @validator('slug', pre=True, always=True)
    def generate_slug_if_missing(cls, v, values):
        """Auto-generate slug from title if not provided"""
        if not v and 'title' in values:
            return generate_slug(values['title'])
        return v


class BlogPostUpdate(BaseModel):
    """Schema for updating a blog post"""
    title: Optional[str] = Field(None, min_length=1, max_length=500)
    slug: Optional[str] = None
    description: Optional[str] = None
    content: Optional[str] = Field(
        None, 
        min_length=1,
        description="Full blog post content in rich text format (HTML or Markdown). "
                   "Supports: headings (H1-H6), bold, italic, underline, strikethrough, "
                   "lists (ordered/unordered), links, code blocks, blockquotes, images, "
                   "and all standard HTML/Markdown formatting."
    )
    
    @validator('content')
    def validate_content(cls, v):
        """Normalize and validate rich text content"""
        if v is not None:
            if not v.strip():
                raise ValueError("Content cannot be empty")
            return normalize_rich_text_content(v)
        return v
    category: Optional[str] = Field(
        None, 
        min_length=1, 
        max_length=100, 
        description="Category tag. Must be one of: Product (updates/features), Productivity (tips/workflows), Education & AI (tutorials/concepts), Business (ROI/case studies), Engineering (technical/API). See /blog/categories/info for details."
    )
    featured_image_url: Optional[str] = None
    is_published: Optional[bool] = None
    published_at: Optional[datetime] = None
    meta_title: Optional[str] = Field(None, max_length=500)
    meta_description: Optional[str] = None
    tags: Optional[List[str]] = None
    
    @validator('category')
    def validate_category(cls, v):
        """Ensure category is one of the allowed categories"""
        if v is not None and v not in ALLOWED_CATEGORIES:
            raise ValueError(f"Category must be one of: {', '.join(ALLOWED_CATEGORIES)}")
        return v


class BlogPostResponse(BlogPostBase):
    """Schema for blog post response"""
    id: int
    slug: str
    is_published: bool
    published_at: Optional[datetime]
    read_time_minutes: int
    created_at: datetime
    updated_at: datetime
    author_id: Optional[int] = None
    author_name: Optional[str] = None
    
    class Config:
        from_attributes = True  # Pydantic v2: replaces from_orm=True


class BlogPostListResponse(BaseModel):
    """Schema for paginated blog post list"""
    posts: List[BlogPostResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


# ============================================
# API ENDPOINTS
# ============================================

@router.post("/posts", response_model=BlogPostResponse, status_code=status.HTTP_201_CREATED)
async def create_blog_post(
    post: BlogPostCreate,
    db: AsyncSession = Depends(get_async_db),
    admin: User = Depends(get_admin_user)
):
    """
    Create a new blog post (admin only)
    
    **Rich Text Content Support:**
    
    The backend accepts rich text content from WYSIWYG editors (HTML) or Markdown editors.
    
    **Supported Formats:**
    - **HTML**: Full HTML support from rich text editors (WYSIWYG)
      - Headings: `<h1>` through `<h6>`
      - Text formatting: `<strong>`, `<em>`, `<u>`, `<s>`, `<mark>`
      - Lists: `<ul>`, `<ol>`, `<li>`
      - Links: `<a href="">`
      - Code: `<code>`, `<pre>`
      - Blockquotes: `<blockquote>`
      - Images: `<img src="">`
      - Paragraphs: `<p>`
      - Line breaks: `<br>`, `<hr>`
      - And all standard HTML elements
    
    - **Markdown**: Full Markdown support
      - Headings: `# H1`, `## H2`, `### H3`, etc.
      - Text formatting: `**bold**`, `*italic*`, `~~strikethrough~~`
      - Lists: `- item` or `1. item`
      - Links: `[text](url)`
      - Code: `` `inline` `` or ` ```code blocks``` ``
      - Blockquotes: `> quote`
      - Images: `![alt](url)`
      - Horizontal rules: `---`
    
    **Content Processing:**
    - Content is stored exactly as received from the frontend editor
    - No automatic conversion or sanitization (frontend should handle sanitization)
    - Whitespace is normalized for consistent storage
    - Read time is calculated by stripping formatting tags
    
    **Structure:**
    - `title`: Main blog post title (shown at top)
    - `description`: Subtitle/lead paragraph (shown below title, before content)
    - `content`: Full blog post body with all formatting (headings, paragraphs, lists, etc.)
    
    **Example Content Structure:**
    ```markdown
    # Section Heading
    
    Paragraph text here.
    
    ## Sub-section Heading
    
    More content with **bold** and *italic* text.
    
    1. Numbered list item
    2. Another item
    
    - Bullet point
    - Another bullet
    ```
    
    **Fields:**
    - **title**: Blog post title (required)
    - **content**: Full blog post content in markdown or HTML (required)
    - **category**: Category name (e.g., "Product", "Engineering") (required)
    - **description**: Subtitle/lead paragraph (optional, shown below title)
    - **slug**: URL-friendly slug (auto-generated from title if not provided)
    - **is_published**: Whether post is published (default: false)
    - **published_at**: Publication date (optional, set automatically if is_published=true)
    - **featured_image_url**: URL to featured image (optional)
    - **meta_title**: SEO title (optional)
    - **meta_description**: SEO description (optional)
    - **tags**: List of tags (optional)
    
    **Read Time**: Automatically calculated based on word count (strips markdown/HTML for accuracy)
    """
    try:
        # Check if slug already exists
        if post.slug:
            stmt = select(BlogPost).where(BlogPost.slug == post.slug)
            result = await db.execute(stmt)
            existing = result.scalar_one_or_none()
            if existing:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Blog post with slug '{post.slug}' already exists"
                )
        
        # Calculate read time
        read_time = calculate_read_time(post.content)
        
        # Set published_at if publishing
        published_at = post.published_at
        if post.is_published and not published_at:
            published_at = datetime.utcnow()
        
        # Create blog post
        db_post = BlogPost(
            title=post.title,
            slug=post.slug or generate_slug(post.title),
            description=post.description,
            content=post.content,
            category=post.category,
            featured_image_url=post.featured_image_url,
            is_published=post.is_published,
            published_at=published_at,
            meta_title=post.meta_title,
            meta_description=post.meta_description,
            tags=post.tags or [],
            read_time_minutes=read_time
        )
        
        db.add(db_post)
        await db.commit()
        await db.refresh(db_post)
        
        logger.info(f"Created blog post: {db_post.slug}")
        
        # Convert to response model
        response = BlogPostResponse.model_validate(db_post)
        if db_post.author:
            response.author_name = db_post.author.name
        
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating blog post: {e}", exc_info=True)
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create blog post: {str(e)}"
        )


@router.get("/posts", response_model=BlogPostListResponse)
async def list_blog_posts(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(10, ge=1, le=100, description="Items per page"),
    category: Optional[str] = Query(None, description="Filter by category"),
    published_only: bool = Query(True, description="Only return published posts"),
    search: Optional[str] = Query(None, description="Search in title and content"),
    db: AsyncSession = Depends(get_async_db)
):
    """
    List blog posts with pagination and filtering
    
    - **page**: Page number (default: 1)
    - **page_size**: Items per page (default: 10, max: 100)
    - **category**: Filter by category (optional)
    - **published_only**: Only return published posts (default: true)
    - **search**: Search query for title/content (optional)
    """
    try:
        # Build query
        stmt = select(BlogPost)
        
        # Filter by published status
        if published_only:
            stmt = stmt.where(BlogPost.is_published == True)
        
        # Filter by category
        if category:
            stmt = stmt.where(BlogPost.category == category)
        
        # Search in title and content
        if search:
            search_term = f"%{search}%"
            stmt = stmt.where(
                or_(
                    BlogPost.title.ilike(search_term),
                    BlogPost.description.ilike(search_term),
                    BlogPost.content.ilike(search_term)
                )
            )
        
        # Get total count
        from sqlalchemy import func
        count_stmt = select(func.count()).select_from(BlogPost)
        if published_only:
            count_stmt = count_stmt.where(BlogPost.is_published == True)
        if category:
            count_stmt = count_stmt.where(BlogPost.category == category)
        if search:
            search_term = f"%{search}%"
            count_stmt = count_stmt.where(
                or_(
                    BlogPost.title.ilike(search_term),
                    BlogPost.description.ilike(search_term),
                    BlogPost.content.ilike(search_term)
                )
            )
        
        count_result = await db.execute(count_stmt)
        total = count_result.scalar_one()
        
        # Apply pagination and ordering
        stmt = stmt.order_by(desc(BlogPost.published_at), desc(BlogPost.created_at))\
                    .offset((page - 1) * page_size)\
                    .limit(page_size)
        
        result = await db.execute(stmt)
        posts = result.scalars().all()
        
        # Convert to response models
        post_responses = []
        for post in posts:
            response = BlogPostResponse.model_validate(post)
            if post.author:
                response.author_name = post.author.name
            post_responses.append(response)
        
        total_pages = (total + page_size - 1) // page_size
        
        return BlogPostListResponse(
            posts=post_responses,
            total=total,
            page=page,
            page_size=page_size,
            total_pages=total_pages
        )
        
    except Exception as e:
        logger.error(f"Error listing blog posts: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list blog posts: {str(e)}"
        )


@router.get("/posts/{post_id}", response_model=BlogPostResponse)
async def get_blog_post(
    post_id: int,
    db: AsyncSession = Depends(get_async_db)
):
    """
    Get a single blog post by ID
    """
    try:
        stmt = select(BlogPost).where(BlogPost.id == post_id)
        result = await db.execute(stmt)
        post = result.scalar_one_or_none()
        
        if not post:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Blog post with ID {post_id} not found"
            )
        
        response = BlogPostResponse.model_validate(post)
        if post.author:
            response.author_name = post.author.name
        
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting blog post {post_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get blog post: {str(e)}"
        )


@router.get("/posts/slug/{slug}", response_model=BlogPostResponse)
async def get_blog_post_by_slug(
    slug: str,
    published_only: bool = Query(True, description="Only return if published"),
    db: AsyncSession = Depends(get_async_db)
):
    """
    Get a blog post by slug (URL-friendly identifier)
    """
    try:
        stmt = select(BlogPost).where(BlogPost.slug == slug)
        
        if published_only:
            stmt = stmt.where(BlogPost.is_published == True)
        
        result = await db.execute(stmt)
        post = result.scalar_one_or_none()
        
        if not post:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Blog post with slug '{slug}' not found"
            )
        
        response = BlogPostResponse.model_validate(post)
        if post.author:
            response.author_name = post.author.name
        
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting blog post by slug '{slug}': {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get blog post: {str(e)}"
        )


@router.put("/posts/{post_id}", response_model=BlogPostResponse)
async def update_blog_post(
    post_id: int,
    post_update: BlogPostUpdate,
    db: AsyncSession = Depends(get_async_db),
    admin: User = Depends(get_admin_user)
):
    """
    Update a blog post (admin only)
    
    Only provided fields will be updated. If content is updated, read_time_minutes will be recalculated.
    """
    try:
        stmt = select(BlogPost).where(BlogPost.id == post_id)
        result = await db.execute(stmt)
        post = result.scalar_one_or_none()
        
        if not post:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Blog post with ID {post_id} not found"
            )
        
        # Check slug uniqueness if updating
        if post_update.slug and post_update.slug != post.slug:
            check_stmt = select(BlogPost).where(
                and_(BlogPost.slug == post_update.slug, BlogPost.id != post_id)
            )
            check_result = await db.execute(check_stmt)
            existing = check_result.scalar_one_or_none()
            if existing:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Blog post with slug '{post_update.slug}' already exists"
                )
        
        # Update fields
        update_data = post_update.dict(exclude_unset=True)
        
        # Recalculate read time if content changed
        if 'content' in update_data:
            update_data['read_time_minutes'] = calculate_read_time(update_data['content'])
        
        # Handle published_at logic
        if 'is_published' in update_data:
            if update_data['is_published'] and not post.published_at:
                update_data['published_at'] = datetime.utcnow()
            elif not update_data['is_published']:
                update_data['published_at'] = None
        
        # Update the post
        for field, value in update_data.items():
            setattr(post, field, value)
        
        post.updated_at = datetime.utcnow()
        
        await db.commit()
        await db.refresh(post)
        
        logger.info(f"Updated blog post: {post.slug}")
        
        response = BlogPostResponse.model_validate(post)
        if post.author:
            response.author_name = post.author.name
        
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating blog post {post_id}: {e}", exc_info=True)
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update blog post: {str(e)}"
        )


@router.delete("/posts/{post_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_blog_post(
    post_id: int,
    db: AsyncSession = Depends(get_async_db),
    admin: User = Depends(get_admin_user)
):
    """
    Delete a blog post (admin only)
    """
    try:
        stmt = select(BlogPost).where(BlogPost.id == post_id)
        result = await db.execute(stmt)
        post = result.scalar_one_or_none()
        
        if not post:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Blog post with ID {post_id} not found"
            )
        
        await db.delete(post)
        await db.commit()
        
        logger.info(f"Deleted blog post: {post.slug}")
        
        return None
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting blog post {post_id}: {e}", exc_info=True)
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete blog post: {str(e)}"
        )


@router.get("/categories", response_model=List[str])
async def get_categories(
    published_only: bool = Query(True, description="Only count published posts"),
    db: AsyncSession = Depends(get_async_db)
):
    """
    Get list of all allowed blog categories
    
    Returns the predefined list of allowed categories:
    - **Product**: Product updates, feature announcements, roadmap, and release notes
    - **Productivity**: Tips, workflows, strategies, and techniques for maximizing productivity
    - **Education & AI**: Tutorials, guides, AI concepts, and educational content about how Clavr works
    - **Business**: ROI, case studies, enterprise value, and business impact
    - **Engineering**: Technical architecture, API documentation, implementation details, and system design
    
    Use `/blog/categories/info` endpoint for detailed category descriptions and content guidance.
    """
    try:
        # Return the allowed categories list
        return ALLOWED_CATEGORIES
        
    except Exception as e:
        logger.error(f"Error getting categories: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get categories: {str(e)}"
        )


@router.get("/categories/info")
async def get_categories_info():
    """
    Get detailed information about each blog category including descriptions and content guidance
    
    Returns a dictionary mapping each category to its description and suggested content types.
    Useful for content creators to understand what content belongs in each category.
    """
    return CATEGORY_DESCRIPTIONS


# ============================================
# TEXT COMPLETION ENDPOINTS
# ============================================

class TextCompletionRequest(BaseModel):
    """Request for text completion"""
    prompt: str = Field(..., min_length=1, description="The text prompt to complete (can be partial text, single word, or incomplete sentence)")
    context: Optional[str] = Field(None, description="Optional context (e.g., existing blog content, title, category)")
    max_tokens: Optional[int] = Field(50, ge=5, le=200, description="Maximum tokens to generate (5-200, default: 50 for real-time typing)")
    temperature: Optional[float] = Field(0.7, ge=0.0, le=1.0, description="Creativity level (0.0 = factual, 1.0 = creative)")
    cursor_position: Optional[int] = Field(None, description="Optional cursor position in the prompt (for better context)")
    last_words: Optional[int] = Field(10, ge=1, le=50, description="Number of last words to use for context (default: 10)")


class TextCompletionResponse(BaseModel):
    """Response for text completion"""
    completion: str
    prompt: str
    tokens_generated: Optional[int] = None


@router.post("/completion", response_model=TextCompletionResponse)
async def complete_text(
    request: TextCompletionRequest,
    user: User = Depends(get_current_user)
):
    """
    Generate text completion suggestions for blog writing (authenticated users)
    
    **Designed for Real-Time Typing:**
    This endpoint works as soon as the user starts typing, even with partial words,
    incomplete sentences, or just a few characters. It's optimized for real-time
    autocomplete scenarios.
    
    **Usage:**
    - Provide a `prompt` with the text the user has typed so far (can be very short)
    - Optionally provide `context` (title, category, existing content) for better suggestions
    - Use `cursor_position` to indicate where the cursor is (for better context)
    - Adjust `max_tokens` for shorter (5-20) or longer (50-200) completions
    - Lower `temperature` (0.3-0.5) for more predictable completions during typing
    - Higher `temperature` (0.7-1.0) for more creative suggestions
    
    **Examples:**
    
    **Short prompt (user just started typing):**
    ```json
    {
      "prompt": "Email",
      "max_tokens": 20,
      "temperature": 0.5
    }
    ```
    
    **Partial sentence:**
    ```json
    {
      "prompt": "Email has become both a blessing",
      "context": "Title: The Email Crisis\nCategory: Product",
      "max_tokens": 50,
      "temperature": 0.7
    }
    ```
    
    **With cursor position:**
    ```json
    {
      "prompt": "Email has become both a blessing and a curse. It's our primary",
      "cursor_position": 45,
      "max_tokens": 50
    }
    ```
    
    **Response:**
    The completion will continue the text naturally from where the user left off,
    maintaining the writing style and context provided. For real-time typing, use
    shorter `max_tokens` (10-30) for faster responses.
    """
    try:
        # Load config and get LLM
        config = load_config()
        max_tokens = request.max_tokens or 50  # Default to 50 for real-time typing
        llm = LLMFactory.get_llm_for_provider(
            config, 
            temperature=request.temperature or 0.7,
            max_tokens=max_tokens
        )
        
        # Extract relevant context from prompt (last N words for better performance)
        prompt_text = request.prompt.strip()
        
        # If cursor position is provided, use text up to cursor
        if request.cursor_position and request.cursor_position > 0:
            prompt_text = prompt_text[:request.cursor_position].strip()
        
        # Extract last N words for context (helps with partial/incomplete text)
        words = prompt_text.split()
        last_words_count = request.last_words or 10  # Default to 10 if not provided
        if len(words) > last_words_count:
            # Use last N words for better context
            context_words = ' '.join(words[-last_words_count:])
        else:
            context_words = prompt_text
        
        # Build the completion prompt optimized for real-time typing
        from src.ai.prompts import BLOG_COMPLETION_SYSTEM, BLOG_COMPLETION_PROMPT
        
        system_prompt = BLOG_COMPLETION_SYSTEM
        
        # Combine context and prompt if context is provided
        if request.context:
            context_text = f"Blog Context:\n{request.context}\n\n"
        else:
            context_text = ""
        
        user_prompt = BLOG_COMPLETION_PROMPT.format(
            context=context_text,
            prompt_text=context_words
        )
        
        # Generate completion
        full_prompt = f"{system_prompt}\n\n{user_prompt}"
        
        try:
            response = llm.invoke(full_prompt)
            
            # Extract completion text
            if hasattr(response, 'content'):
                completion = response.content
            elif isinstance(response, str):
                completion = response
            else:
                completion = str(response)
            
            # Clean up the completion (remove any prompt repetition)
            completion = completion.strip()
            
            # Remove common prefixes that might be added
            prefixes_to_remove = [
                "Current text (user is typing):",
                "Text to complete:",
                "Completion:",
                "Suggested completion:",
            ]
            for prefix in prefixes_to_remove:
                if completion.lower().startswith(prefix.lower()):
                    completion = completion[len(prefix):].strip()
            
            # Remove the original prompt if it was included in the response
            prompt_lower = context_words.lower()
            completion_lower = completion.lower()
            
            # If completion starts with the prompt, remove it
            if completion_lower.startswith(prompt_lower):
                completion = completion[len(context_words):].strip()
            # If prompt is somewhere in completion, try to extract only new part
            elif prompt_lower in completion_lower:
                # Find where prompt ends and take everything after
                idx = completion_lower.find(prompt_lower)
                if idx >= 0:
                    completion = completion[idx + len(context_words):].strip()
            
            # For very short prompts, ensure we get a meaningful completion
            if len(prompt_text.split()) <= 2 and len(completion.split()) <= 2:
                # If completion is too short, it might just be completing the word
                # This is fine for real-time typing scenarios
                pass
            
            # Ensure completion is not empty
            if not completion:
                # Fallback: generate a simple continuation
                completion = "..."
            
            # Estimate tokens (rough approximation: 1 token ≈ 4 characters)
            tokens_generated = len(completion) // 4
            
            logger.info(f"Generated text completion for user {user.email} ({tokens_generated} tokens)")
            
            return TextCompletionResponse(
                completion=completion,
                prompt=request.prompt,
                tokens_generated=tokens_generated
            )
            
        except Exception as e:
            logger.error(f"LLM completion error: {e}", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to generate completion: {str(e)}"
            )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in text completion: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to complete text: {str(e)}"
        )

