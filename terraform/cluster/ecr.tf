# --- Image registry (design 8.1) -----------------------------------------------------------------

resource "aws_ecr_repository" "app" {
  name                 = "shiptrack/app"
  image_tag_mutability = "IMMUTABLE"

  encryption_configuration {
    encryption_type = "KMS"
    kms_key         = module.eks.kms_key_arn
  }

  image_scanning_configuration {
    # Inspector enhanced scanning is enabled for the account by the platform; this is the basic
    # scan on push that remains available without it.
    scan_on_push = true
  }
}

resource "aws_ecr_lifecycle_policy" "app" {
  repository = aws_ecr_repository.app.name

  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Expire untagged images after one day"
        selection = {
          tagStatus   = "untagged"
          countType   = "sinceImagePushed"
          countUnit   = "days"
          countNumber = 1
        }
        action = { type = "expire" }
      },
      {
        rulePriority = 2
        description  = "Keep the latest 30 images tagged sha-*"
        selection = {
          tagStatus     = "tagged"
          tagPrefixList = ["sha-"]
          countType     = "imageCountMoreThan"
          countNumber   = 30
        }
        action = { type = "expire" }
      },
    ]
  })
}

data "aws_iam_policy_document" "ecr" {
  statement {
    sid    = "SameAccountPull"
    effect = "Allow"
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:BatchGetImage",
      "ecr:GetDownloadUrlForLayer",
    ]

    principals {
      type        = "AWS"
      identifiers = ["arn:${local.partition}:iam::${local.account}:root"]
    }
  }
}

resource "aws_ecr_repository_policy" "app" {
  repository = aws_ecr_repository.app.name
  policy     = data.aws_iam_policy_document.ecr.json
}
