import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Category, CategoryGroup, Tag, Transaction
from app.schemas import (
    CategoryCreate,
    CategoryGroupCreate,
    CategoryGroupResponse,
    CategoryGroupUpdate,
    CategoryResponse,
    CategoryUpdate,
    TagCreate,
    TagResponse,
    TagUpdate,
)
from app.security import AuthContext, current_auth
from app.services.security_audit import record_security_event

router = APIRouter(prefix="/categories", tags=["categories"])


def _require_editor(auth: AuthContext) -> None:
    if auth.role == "viewer":
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "View-only household members cannot change categories",
        )


async def _household_group(
    db: AsyncSession, household_id: uuid.UUID, group_id: uuid.UUID
) -> CategoryGroup:
    group = await db.scalar(
        select(CategoryGroup).where(
            CategoryGroup.id == group_id,
            CategoryGroup.household_id == household_id,
        )
    )
    if not group:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Category group not found")
    return group


async def _household_category(
    db: AsyncSession, household_id: uuid.UUID, category_id: uuid.UUID
) -> Category:
    category = await db.scalar(
        select(Category).where(
            Category.id == category_id,
            Category.household_id == household_id,
        )
    )
    if not category:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Category not found")
    return category


async def _household_tag(
    db: AsyncSession, household_id: uuid.UUID, tag_id: uuid.UUID
) -> Tag:
    tag = await db.scalar(
        select(Tag).where(Tag.id == tag_id, Tag.household_id == household_id)
    )
    if not tag:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tag not found")
    return tag


@router.get("", response_model=list[CategoryResponse])
async def list_categories(
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    rows = await db.execute(
        select(Category, CategoryGroup)
        .join(CategoryGroup, Category.group_id == CategoryGroup.id)
        .where(
            Category.household_id == auth.household_id,
            Category.is_archived.is_(False),
        )
        .order_by(CategoryGroup.sort_order.asc(), Category.name.asc())
    )
    return [
        CategoryResponse(
            id=category.id,
            group_id=group.id,
            group_name=group.name,
            group_is_income=group.is_income,
            name=category.name,
            color=category.color,
            icon=category.icon,
            flex_bucket=category.flex_bucket,
            excluded_from_budget=category.excluded_from_budget,
            budget_month_offset=category.budget_month_offset,
        )
        for category, group in rows
    ]


@router.get("/tags", response_model=list[TagResponse])
async def list_tags(
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    return (
        await db.scalars(
            select(Tag)
            .where(Tag.household_id == auth.household_id)
            .order_by(Tag.name.asc())
        )
    ).all()


@router.post("/tags", response_model=TagResponse, status_code=201)
async def create_tag(
    payload: TagCreate,
    request: Request,
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    _require_editor(auth)
    name = payload.name.strip()
    if not name:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Tag name is required",
        )
    tag = Tag(household_id=auth.household_id, name=name, color=payload.color)
    db.add(tag)
    try:
        await db.flush()
        await record_security_event(
            db,
            "finance.tag_created",
            request=request,
            household_id=auth.household_id,
            user_id=auth.user.id,
            details={"tag_id": tag.id},
        )
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, "A tag with that name already exists"
        ) from exc
    await db.refresh(tag)
    return tag


@router.patch("/tags/{tag_id}", response_model=TagResponse)
async def update_tag(
    tag_id: uuid.UUID,
    payload: TagUpdate,
    request: Request,
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    _require_editor(auth)
    tag = await _household_tag(db, auth.household_id, tag_id)
    if "name" in payload.model_fields_set and payload.name is not None:
        name = payload.name.strip()
        if not name:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, "Tag name is required"
            )
        tag.name = name
    if "color" in payload.model_fields_set and payload.color is not None:
        tag.color = payload.color
    try:
        await record_security_event(
            db,
            "finance.tag_updated",
            request=request,
            household_id=auth.household_id,
            user_id=auth.user.id,
            details={
                "tag_id": tag.id,
                "fields": ",".join(sorted(payload.model_fields_set)),
            },
        )
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, "A tag with that name already exists"
        ) from exc
    await db.refresh(tag)
    return tag


@router.delete("/tags/{tag_id}", status_code=204)
async def delete_tag(
    tag_id: uuid.UUID,
    request: Request,
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    _require_editor(auth)
    tag = await _household_tag(db, auth.household_id, tag_id)
    await db.delete(tag)
    await record_security_event(
        db,
        "finance.tag_deleted",
        request=request,
        household_id=auth.household_id,
        user_id=auth.user.id,
        details={"tag_id": tag.id},
    )
    await db.commit()


@router.get("/groups", response_model=list[CategoryGroupResponse])
async def list_groups(
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    rows = await db.execute(
        select(CategoryGroup, func.count(Category.id))
        .outerjoin(
            Category,
            (Category.group_id == CategoryGroup.id)
            & Category.is_archived.is_(False),
        )
        .where(CategoryGroup.household_id == auth.household_id)
        .group_by(CategoryGroup.id)
        .order_by(CategoryGroup.sort_order.asc(), CategoryGroup.name.asc())
    )
    return [
        CategoryGroupResponse(
            id=group.id,
            name=group.name,
            is_income=group.is_income,
            sort_order=group.sort_order,
            category_count=count,
        )
        for group, count in rows
    ]


@router.post("/groups", response_model=CategoryGroupResponse, status_code=201)
async def create_group(
    payload: CategoryGroupCreate,
    request: Request,
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    _require_editor(auth)
    last = await db.scalar(
        select(func.max(CategoryGroup.sort_order)).where(
            CategoryGroup.household_id == auth.household_id
        )
    )
    group = CategoryGroup(
        household_id=auth.household_id,
        name=payload.name,
        is_income=payload.is_income,
        sort_order=(last or 0) + 1,
    )
    db.add(group)
    try:
        await db.flush()
        await record_security_event(
            db,
            "finance.category_group_created",
            request=request,
            household_id=auth.household_id,
            user_id=auth.user.id,
            details={"group_id": group.id},
        )
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, "A group with that name already exists"
        ) from exc
    await db.refresh(group)
    return CategoryGroupResponse(
        id=group.id,
        name=group.name,
        is_income=group.is_income,
        sort_order=group.sort_order,
        category_count=0,
    )


@router.patch("/groups/{group_id}", response_model=CategoryGroupResponse)
async def update_group(
    group_id: uuid.UUID,
    payload: CategoryGroupUpdate,
    request: Request,
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    _require_editor(auth)
    group = await _household_group(db, auth.household_id, group_id)
    for field in ("name", "is_income", "sort_order"):
        if field in payload.model_fields_set:
            value = getattr(payload, field)
            if value is not None:
                setattr(group, field, value)
    try:
        await record_security_event(
            db,
            "finance.category_group_updated",
            request=request,
            household_id=auth.household_id,
            user_id=auth.user.id,
            details={
                "group_id": group.id,
                "fields": ",".join(sorted(payload.model_fields_set)),
            },
        )
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, "A group with that name already exists"
        ) from exc
    await db.refresh(group)
    count = (
        await db.scalar(
            select(func.count(Category.id)).where(
                Category.group_id == group.id,
                Category.is_archived.is_(False),
            )
        )
    ) or 0
    return CategoryGroupResponse(
        id=group.id,
        name=group.name,
        is_income=group.is_income,
        sort_order=group.sort_order,
        category_count=count,
    )


@router.delete("/groups/{group_id}", status_code=204)
async def delete_group(
    group_id: uuid.UUID,
    request: Request,
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    _require_editor(auth)
    group = await _household_group(db, auth.household_id, group_id)
    remaining = (
        await db.scalar(
            select(func.count(Category.id)).where(
                Category.group_id == group.id,
                Category.is_archived.is_(False),
            )
        )
    ) or 0
    if remaining:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Move or archive the {remaining} categories in this group first",
        )
    await db.delete(group)
    await record_security_event(
        db,
        "finance.category_group_deleted",
        request=request,
        household_id=auth.household_id,
        user_id=auth.user.id,
        details={"group_id": group.id},
    )
    await db.commit()


@router.post("", response_model=CategoryResponse, status_code=201)
async def create_category(
    payload: CategoryCreate,
    request: Request,
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    _require_editor(auth)
    group = await _household_group(db, auth.household_id, payload.group_id)
    category = Category(
        household_id=auth.household_id,
        group_id=group.id,
        name=payload.name,
        color=payload.color,
        flex_bucket=payload.flex_bucket,
    )
    db.add(category)
    try:
        await db.flush()
        await record_security_event(
            db,
            "finance.category_created",
            request=request,
            household_id=auth.household_id,
            user_id=auth.user.id,
            details={"category_id": category.id, "group_id": group.id},
        )
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, "A category with that name already exists"
        ) from exc
    await db.refresh(category)
    return CategoryResponse(
        id=category.id,
        group_id=group.id,
        group_name=group.name,
        group_is_income=group.is_income,
        name=category.name,
        color=category.color,
        icon=category.icon,
        flex_bucket=category.flex_bucket,
        excluded_from_budget=category.excluded_from_budget,
        budget_month_offset=category.budget_month_offset,
    )


@router.patch("/{category_id}", response_model=CategoryResponse)
async def update_category(
    category_id: uuid.UUID,
    payload: CategoryUpdate,
    request: Request,
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    _require_editor(auth)
    category = await _household_category(db, auth.household_id, category_id)
    if "group_id" in payload.model_fields_set and payload.group_id:
        await _household_group(db, auth.household_id, payload.group_id)
        category.group_id = payload.group_id
    for field in (
        "name",
        "color",
        "flex_bucket",
        "is_archived",
        "excluded_from_budget",
        "budget_month_offset",
    ):
        if field in payload.model_fields_set:
            value = getattr(payload, field)
            if value is not None:
                setattr(category, field, value)
    try:
        await record_security_event(
            db,
            "finance.category_updated",
            request=request,
            household_id=auth.household_id,
            user_id=auth.user.id,
            details={
                "category_id": category.id,
                "fields": ",".join(sorted(payload.model_fields_set)),
            },
        )
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, "A category with that name already exists"
        ) from exc
    await db.refresh(category)
    group = await db.get(CategoryGroup, category.group_id)
    return CategoryResponse(
        id=category.id,
        group_id=category.group_id,
        group_name=group.name if group else "",
        group_is_income=group.is_income if group else False,
        name=category.name,
        color=category.color,
        icon=category.icon,
        flex_bucket=category.flex_bucket,
        excluded_from_budget=category.excluded_from_budget,
        budget_month_offset=category.budget_month_offset,
    )


@router.delete("/{category_id}", status_code=204)
async def delete_category(
    category_id: uuid.UUID,
    request: Request,
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    """
    Archive rather than delete when history exists. Removing a category that
    transactions point at would silently rewrite past reports, so a used
    category is hidden and its records keep their meaning.
    """
    _require_editor(auth)
    category = await _household_category(db, auth.household_id, category_id)
    used = (
        await db.scalar(
            select(func.count(Transaction.id)).where(
                Transaction.category_id == category.id
            )
        )
    ) or 0
    if used:
        category.is_archived = True
    else:
        await db.delete(category)
    await record_security_event(
        db,
        "finance.category_archived" if used else "finance.category_deleted",
        request=request,
        household_id=auth.household_id,
        user_id=auth.user.id,
        details={"category_id": category.id, "transactions": used},
    )
    await db.commit()
